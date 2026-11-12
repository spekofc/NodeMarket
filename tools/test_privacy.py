"""Privacy & buyer-data audit suite: proves the PGP-before-persistence
invariants and the fail-closed behavior end to end.

Run with the server already up on 127.0.0.1:8000 and a FRESH database.
Stdlib + pgpy only. Checks:

 1. encrypt_for_store round-trips (decrypt with the private key).
 2. A key that parses but cannot encrypt is rejected BEFORE any INSERT
    (fail closed) - 400, not 500, no new row.
 3. Buyer plaintext never touches disk: the .db and .db-wal files do not
    contain the marker string; the ciphertext does.
 4. The stored ciphertext decrypts back to exactly the buyer input.
 5. /order/<token> and the admin order page never render the plaintext.
 6. The checkout error re-render never echoes the delivery details.
 7. Invalid / missing keys fail closed: no new order row, no 500.
"""

import re
import sys
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
import sqlite3
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = "http://127.0.0.1:8000"
MARKER = "RUA-SECRETA-42 Avenida Paulista 1578 Sao Paulo"

results = []


def check(name, ok, extra=""):
    results.append((name, ok, _last_html))
    print(("OK  " if ok else "FAIL") + f" {name}" + (f"  [{extra}]" if extra and not ok else ""))


_last_html = ""


def _resp(opener, req):
    global _last_html
    try:
        r = opener.open(req)
        _last_html = r.read().decode()
        return r.status, _last_html, r.geturl()
    except urllib.error.HTTPError as exc:
        _last_html = exc.read().decode()
        return exc.code, _last_html, exc.geturl()


def get(path):
    return _resp(opener, urllib.request.Request(BASE + path))


def post(path, data, with_opener=None):
    op = with_opener or opener
    body = urllib.parse.urlencode(data).encode()
    return _resp(op, urllib.request.Request(BASE + path, data=body, method="POST"))


def solve_captcha(html):
    m = re.search(r'/captcha\.svg\?token=([A-Za-z0-9_-]+)', html)
    if not m:
        return None, None
    token = m.group(1)
    status, svg, _ = get(f"/captcha.svg?token={token}")
    assert status == 200
    glyphs = re.findall(r"<text [^>]*>([^<]+)</text>", svg)
    q = "".join(glyphs)
    m2 = re.match(r"^(\d+)\s*([+\-])\s*(\d+)$", q)
    if not m2:
        raise AssertionError(f"unparseable question: {q!r}")
    a, op, b = int(m2.group(1)), m2.group(2), int(m2.group(3))
    return token, str(a + b if op == "+" else a - b)


# --- crypto layer (in-process, no server) ------------------------------------

sys.path.insert(0, ".")
from app import pgp_compat  # noqa: E402,F401
from app.pgp import encrypt_for_store, validate_public_key  # noqa: E402
from pgpy import PGPKey, PGPUID, PGPMessage  # noqa: E402
from pgpy.constants import (PubKeyAlgorithm, KeyFlags, HashAlgorithm,  # noqa: E402
                            SymmetricKeyAlgorithm, CompressionAlgorithm)


def make_key(algo, flags):
    key = PGPKey.new(algo, 2048)
    uid = PGPUID.new("Audit <audit@test.local>")
    key.add_uid(uid, usage=flags,
                hashes=[HashAlgorithm.SHA256],
                ciphers=[SymmetricKeyAlgorithm.AES256],
                compression=[CompressionAlgorithm.ZLIB])
    return key


good_key = make_key(PubKeyAlgorithm.RSAEncryptOrSign,
                    {KeyFlags.Sign, KeyFlags.EncryptCommunications,
                     KeyFlags.EncryptStorage})
sign_only_key = make_key(PubKeyAlgorithm.RSASign, {KeyFlags.Sign})
GOOD_ARMOR = str(good_key.pubkey)
SIGN_ONLY_ARMOR = str(sign_only_key.pubkey)

ct = encrypt_for_store(GOOD_ARMOR, MARKER)


def decrypt_to_plaintext(ciphertext):
    """Parse armored ciphertext properly (PGPMessage.new would treat the
    armor itself as literal payload) and decrypt with the private key."""
    msg = PGPMessage()
    msg.parse(ciphertext)
    return str(good_key.decrypt(msg).message)


check("round-trip: encrypt -> decrypt == plaintext", MARKER in decrypt_to_plaintext(ct))
check("ciphertext is ASCII-armored", "BEGIN PGP MESSAGE" in ct)
ok, msg = validate_public_key(GOOD_ARMOR)
check("validate_public_key accepts good key", ok)
ok, msg = validate_public_key("")
check("validate_public_key rejects empty", not ok)
ok, msg = validate_public_key("-----BEGIN GARBAGE-----")
check("validate_public_key rejects garbage", not ok)

unencryptable_raised = False
try:
    encrypt_for_store(SIGN_ONLY_ARMOR, MARKER)
except Exception:
    unencryptable_raised = True
check("sign-only key cannot encrypt (raises)", unencryptable_raised)

# --- server session ----------------------------------------------------------

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

status, html, _ = get("/admin/login")
token, answer = solve_captcha(html)
status, html, _ = post("/admin/login", {"captcha_token": token,
                                        "captcha_answer": answer,
                                        "password": "changeme-admin"})
check("admin login", status == 200)

# seed one product (fresh DB => id 1, used by place_order)
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("INSERT INTO products (name, description, price_cents) "
             "VALUES ('Audit Product', 'a', 100)")
conn.commit()
conn.close()


def save_settings(pgp_armor=GOOD_ARMOR):
    data = {
        "store_name": "NodeMarket Store",
        "settlement_mode": "direct",
        "demo_enabled": "on",
    }
    if pgp_armor:
        data["pgp_public_key"] = pgp_armor
    return post("/admin/settings", data)


buyer = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def place_order(delivery_text, wrong_captcha=False):
    body = urllib.parse.urlencode({"pid": "1", "qty": "1"}).encode()
    _resp(buyer, urllib.request.Request(BASE + "/cart/add", data=body, method="POST"))
    status, html, _ = _resp(buyer, urllib.request.Request(BASE + "/checkout"))
    token, answer = solve_captcha(html)
    if wrong_captcha:
        answer = "0"
    body = urllib.parse.urlencode({"delivery_details": delivery_text,
                                   "payment_method": "demo",
                                   "captcha_token": token or "x",
                                   "captcha_answer": answer or "0"}).encode()
    return _resp(buyer, urllib.request.Request(BASE + "/checkout", data=body, method="POST"))


def order_count():
    conn = sqlite3.connect("data/nodemarket.db")
    n = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()
    return n


def buyer_get(path):
    """GET with the buyer's cart cookie (admin jar has no cart)."""
    return _resp(buyer, urllib.request.Request(BASE + path))


save_settings()

# 1. valid checkout with marker plaintext
status, html, url = place_order(MARKER)
check("valid checkout -> order page", "/order/" in url)
order_ref = url.rsplit("/", 1)[-1]

# 2. plaintext never on disk
db_bytes = Path("data/nodemarket.db").read_bytes()
wal_bytes = Path("data/nodemarket.db-wal").read_bytes() \
    if Path("data/nodemarket.db-wal").exists() else b""
check("marker NOT in .db file", MARKER.encode() not in db_bytes)
check("marker NOT in .db-wal file", MARKER.encode() not in wal_bytes)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT buyer_encrypted FROM orders WHERE order_ref = ?",
                   (order_ref,)).fetchone()
conn.close()
check("row exists with PGP ciphertext", row is not None
      and "BEGIN PGP MESSAGE" in row[0])

# 3. ciphertext decrypts back to the marker (at-rest round-trip)
check("stored ciphertext decrypts to buyer input",
      MARKER in decrypt_to_plaintext(row[0]))

# 4. plaintext never rendered
status, html, _ = get(f"/order/{order_ref}")
check("order page has no plaintext", MARKER not in html)
check("order page shows encryption notice", "PGP-encrypted" in html)
check("order page zero script", "<script" not in html)

# 5. admin page shows ciphertext only
status, html, _ = get(f"/admin/orders/{order_ref}")
check("admin page has no plaintext", MARKER not in html)
check("admin page shows ciphertext block", "BEGIN PGP MESSAGE" in html)

# 6. captcha-error re-render must not echo delivery details
status, html, _ = place_order(MARKER, wrong_captcha=True)
check("bad captcha -> 400", status == 400)
check("error page does not echo delivery details", MARKER not in html)

# 7. fail closed: key that parses but cannot encrypt
baseline = order_count()
save_settings(pgp_armor=SIGN_ONLY_ARMOR)
status, html, _ = buyer_get("/checkout")
check("sign-only key accepted by validator (captcha shown)", "/captcha.svg?token=" in html)
status, html, url = place_order(MARKER)
check("unencryptable key -> 400 (fail closed, not 500)", status == 400)
check("no order row on unencryptable key", order_count() == baseline)

# 8. fail closed: garbage key
save_settings(pgp_armor="-----BEGIN GARBAGE-----")
status, html, _ = buyer_get("/checkout")
check("garbage key -> warning on checkout page", "cannot be placed yet" in html)
status, html, url = place_order(MARKER)
check("garbage key -> 400", status == 400)
check("no order row on garbage key", order_count() == baseline)

# 9. fail closed: missing key
save_settings(pgp_armor="")
status, html, _ = buyer_get("/checkout")
check("missing key -> warning on checkout page", "cannot be placed yet" in html)
status, html, url = place_order(MARKER)
check("missing key -> 400", status == 400)
check("no order row on missing key", order_count() == baseline)

# restore valid settings
save_settings()
check("final order count == 1 (no leaks created rows)", order_count() == 1)

print()
failed = [(n, h) for (n, ok, h) in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
for n, h in failed:
    print("\n---- FAILED:", n)
    print((h or "")[:600])
sys.exit(1 if failed else 0)
