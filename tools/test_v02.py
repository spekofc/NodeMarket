"""v0.2 end-to-end test: captcha-gated admin login and checkout, rate limits.

Run with the server already up on 127.0.0.1:8000.
Uses only stdlib. Solves the SVG captcha by parsing the glyph text nodes
(simulating a human reading the image).
"""

import re
import sys
import urllib.parse
import urllib.request
import http.cookiejar
import warnings

warnings.filterwarnings("ignore")

BASE = "http://127.0.0.1:8000"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def get(path, expect=200):
    try:
        resp = opener.open(BASE + path)
        return resp.status, resp.read().decode(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), dict(exc.headers)


def post(path, data, expect=None):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    try:
        resp = opener.open(req)
        return resp.status, resp.read().decode(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), dict(exc.headers)


def solve_captcha(html):
    """Extract token from the page, fetch the SVG, parse glyphs, return answer."""
    m = re.search(r'/captcha\.svg\?token=([A-Za-z0-9_-]+)', html)
    if not m:
        return None, None
    token = m.group(1)
    status, svg, _ = get(f"/captcha.svg?token={token}")
    assert status == 200, f"captcha svg status {status}"
    glyphs = re.findall(r"<text [^>]*>([^<]+)</text>", svg)
    q = "".join(glyphs)
    m2 = re.match(r"^(\d+)\s*([+\-])\s*(\d+)$", q)
    if not m2:
        raise AssertionError(f"unparseable question: {q!r}")
    a, op, b = int(m2.group(1)), m2.group(2), int(m2.group(3))
    return token, str(a + b if op == "+" else a - b)


results = []


def check(name, ok):
    results.append((name, ok))
    print(("OK  " if ok else "FAIL") + f" {name}")


# --- admin login flow -------------------------------------------------------

status, html, _ = get("/admin/login")
check("login page has captcha img", "/captcha.svg?token=" in html)
check("login page has hidden token input", 'name="captcha_token"' in html)
check("js banner present", "js-banner" in html)
check("noscript hides banner", "js-banner{display:none" in html)

token, answer = solve_captcha(html)
check("captcha solved from svg", answer is not None)
print(f"     question answer: {answer}")

status, html, _ = post("/admin/login",
                       {"captcha_token": token, "captcha_answer": "99",
                        "password": "changeme-admin"})
check("wrong captcha -> 401", status == 401)
check("error page offers fresh token", "/captcha.svg?token=" in html)

# redo with correct answer (the failed attempt consumed nothing, token intact;
# but be safe: fetch a fresh one)
status, html, _ = get("/admin/login")
token, answer = solve_captcha(html)
status, html, headers = post("/admin/login",
                             {"captcha_token": token, "captcha_answer": answer,
                              "password": "changeme-admin"})
check("correct captcha + password -> login", status == 200 and "nm_admin" in str(cj))

# single-use replay
status, html, _ = post("/admin/login",
                       {"captcha_token": token, "captcha_answer": answer,
                        "password": "changeme-admin"})
check("captcha replay rejected", status == 401)

status, html, _ = get("/admin")
check("admin dashboard accessible", status == 200 and "Admin" in html)

# --- checkout flow -----------------------------------------------------------

# set store pgp key + product via admin session
sys.path.insert(0, ".")
from app import pgp_compat  # noqa: E402,F401  (imghdr shim before pgpy)
from pgpy import PGPKey, PGPUID  # noqa: E402
from pgpy.constants import (PubKeyAlgorithm, KeyFlags, HashAlgorithm,
                            SymmetricKeyAlgorithm, CompressionAlgorithm)

key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
uid = PGPUID.new("NodeMarket Test <store@test.local>")
key.add_uid(uid, usage={KeyFlags.Sign, KeyFlags.EncryptCommunications,
                        KeyFlags.EncryptStorage},
            hashes=[HashAlgorithm.SHA256],
            ciphers=[SymmetricKeyAlgorithm.AES256],
            compression=[CompressionAlgorithm.ZLIB, CompressionAlgorithm.ZIP,
                         CompressionAlgorithm.Uncompressed])
pub_armor = str(key.pubkey)
import sqlite3  # noqa: E402
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("UPDATE store_settings SET pgp_public_key = ?, payment_provider = 'demo' WHERE id = 1",
             (pub_armor,))
conn.execute("INSERT INTO products (name, description, price_cents) VALUES ('Test Widget', 'A fine widget.', 999)")
conn.commit()
conn.close()

# buyer session: add to cart
import urllib.request as _u
buyer_cj = http.cookiejar.CookieJar()
buyer = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(buyer_cj))


def buyer_post(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    return buyer.open(req)


buyer_post("/cart/add", {"pid": "1", "qty": "2"})

status, html, _ = buyer.open(BASE + "/checkout").read().decode(), None, None
status, html, _ = None, buyer.open(BASE + "/checkout").read().decode(), None
check("checkout page has captcha", "/captcha.svg?token=" in html)

token, answer = solve_captcha(html)

# wrong captcha -> 400 with error, fresh token
body = urllib.parse.urlencode({"delivery_details": "Rua Teste 123",
                               "captcha_token": token, "captcha_answer": "0"}).encode()
req = urllib.request.Request(BASE + "/checkout", data=body, method="POST")
try:
    resp = buyer.open(req)
    code = resp.status
    page = resp.read().decode()
except urllib.error.HTTPError as exc:
    code = exc.code
    page = exc.read().decode()
check("wrong checkout captcha -> 400", code == 400)
check("checkout error shown", "Wrong or expired captcha" in page)
check("fresh token in error page", "/captcha.svg?token=" in page)

# correct captcha -> order created
token, answer = solve_captcha(page)
body = urllib.parse.urlencode({"delivery_details": "Rua Teste 123, Sao Paulo",
                               "captcha_token": token, "captcha_answer": answer}).encode()
req = urllib.request.Request(BASE + "/checkout", data=body, method="POST")
resp = buyer.open(req)
final = resp.geturl()
check("checkout redirected to order", "/order/" in final)
order_html = resp.read().decode()
check("no plaintext in order page", "Rua Teste" not in order_html)

# plaintext must not be in the db
conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT buyer_encrypted FROM orders ORDER BY id DESC LIMIT 1").fetchone()
check("buyer data stored as PGP ciphertext", "BEGIN PGP MESSAGE" in row[0])
n_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
conn.close()

# --- rate limits -------------------------------------------------------------

# admin login limit is 5/min; we already used ~3. Hammer until 429.
codes = []
for i in range(8):
    body = urllib.parse.urlencode({"captcha_token": "x", "captcha_answer": "1",
                                   "password": "wrong"}).encode()
    req = urllib.request.Request(BASE + "/admin/login", data=body, method="POST")
    try:
        r = urllib.request.urlopen(req)
        codes.append(r.status)
        r.read()
    except urllib.error.HTTPError as exc:
        codes.append(exc.code)
        exc.read()
check("admin login rate limited (429 seen)", 429 in codes)
print(f"     login post codes: {codes}")

# captcha svg limit is 30/min
codes = []
for i in range(35):
    try:
        r = urllib.request.urlopen(BASE + "/captcha.svg?token=zzz")
        codes.append(r.status)
        r.read()
    except urllib.error.HTTPError as exc:
        codes.append(exc.code)
        exc.read()
check("captcha svg rate limited (429 seen)", 429 in codes)
print(f"     svg codes tail: {codes[-4:]}")

print()
failed = [n for n, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
