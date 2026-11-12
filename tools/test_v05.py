"""v0.5 suite: order messaging (buyer↔seller) and product reporting.

Run with server on 127.0.0.1:8000, fresh DB.
"""

import re
import sys
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
import sqlite3
import warnings

warnings.filterwarnings("ignore")

# pgp_compat must be imported before pgpy to install imghdr shim
sys.path.insert(0, ".")
from app import pgp_compat  # noqa: F401,E402
from pgpy import PGPKey, PGPUID
from pgpy.constants import PubKeyAlgorithm, KeyFlags, HashAlgorithm, SymmetricKeyAlgorithm, CompressionAlgorithm

BASE = "http://127.0.0.1:8000"
results = []


def check(name, ok, extra=""):
    results.append((name, ok))
    print(("OK  " if ok else "FAIL") + f" {name}" + (f"  [{extra}]" if extra and not ok else ""))


def _resp(opener, req):
    try:
        r = opener.open(req)
        return r.status, r.read().decode(), r.geturl()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), exc.geturl()


def get(path):
    return _resp(opener, urllib.request.Request(BASE + path))


def buyer_get(path):
    return _resp(buyer, urllib.request.Request(BASE + path))


def buyer_post(path, data):
    body = urllib.parse.urlencode(data).encode()
    return _resp(buyer, urllib.request.Request(BASE + path, data=body, method="POST"))


def admin_post(path, data):
    body = urllib.parse.urlencode(data).encode()
    return _resp(opener, urllib.request.Request(BASE + path, data=body, method="POST"))


def solve_captcha(html):
    m = re.search(r'/captcha\.svg\?token=([A-Za-z0-9_-]+)', html)
    if not m:
        return None, None
    token = m.group(1)
    status, svg, _ = get(f"/captcha.svg?token={token}")
    glyphs = re.findall(r"<text [^>]*>([^<]+)</text>", svg)
    q = "".join(glyphs)
    m2 = re.match(r"^(\d+)\s*([+\-])\s*(\d+)$", q)
    if not m2:
        raise AssertionError(f"unparseable question: {q!r}")
    a, op, b = int(m2.group(1)), m2.group(2), int(m2.group(3))
    return token, str(a + b if op == "+" else a - b)


def place_order(delivery="Test address", method="demo", pgp_mode="plain", pgp_block=""):
    buyer_post("/cart/add", {"pid": "1", "qty": "1"})
    status, html, _ = buyer_get("/checkout")
    token, answer = solve_captcha(html)
    data = {"delivery_details": delivery, "payment_method": method,
            "pgp_mode": pgp_mode, "pgp_block": pgp_block,
            "captcha_token": token, "captcha_answer": answer}
    return buyer_post("/checkout", data)


def order_count():
    conn = sqlite3.connect("data/nodemarket.db")
    n = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()
    return n


def message_count(order_id):
    conn = sqlite3.connect("data/nodemarket.db")
    n = conn.execute("SELECT COUNT(*) FROM order_messages WHERE order_id = ?", (order_id,)).fetchone()[0]
    conn.close()
    return n


# --- setup ---
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
buyer = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

status, html, _ = get("/admin/login")
token, answer = solve_captcha(html)
status, html, _ = admin_post("/admin/login", {"captcha_token": token,
                                              "captcha_answer": answer,
                                              "password": "changeme-admin"})
check("admin login", status == 200)

# seed 1 product
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("INSERT INTO products (name, description, price_cents) "
             "VALUES ('Test Product', 'A product for testing', 1000)")
conn.commit()
conn.close()

# admin settings: enable demo, set a valid PGP key
store_key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
store_key.add_uid(PGPUID.new("Store <store@test.local>"),
                  usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
                  hashes=[HashAlgorithm.SHA256], ciphers=[SymmetricKeyAlgorithm.AES256],
                  compression=[CompressionAlgorithm.ZLIB])
STORE_PUB = str(store_key.pubkey)

admin_post("/admin/settings", {
    "store_name": "NodeMarket Store",
    "settlement_mode": "direct",
    "demo_enabled": "on",
    "pgp_public_key": STORE_PUB,
})


# ============================================================
# 1. ORDER MESSAGING
# ============================================================

# buyer places order
status, html, url = place_order()
check("order placed", status == 200 and "/order/" in url)
order_ref = url.rsplit("/", 1)[-1]

# get order_id
conn = sqlite3.connect("data/nodemarket.db")
order_id = conn.execute("SELECT id FROM orders WHERE order_ref = ?", (order_ref,)).fetchone()[0]
conn.close()

# GET messages page (empty)
status, html, _ = buyer_get(f"/order/{order_ref}/messages")
check("messages page loads", status == 200)
check("messages page shows order ref", order_ref in html)

# buyer sends encrypted message (default)
status, html, _ = buyer_get(f"/order/{order_ref}/messages")
token, answer = solve_captcha(html)
status, html, url = buyer_post(f"/order/{order_ref}/messages", {
    "body": "Hello, when will this ship?",
    "pgp_mode": "encrypt",
    "captcha_token": token, "captcha_answer": answer
})
check("buyer sends encrypted message", status == 200 and "/messages" in url)
check("message count = 1", message_count(order_id) == 1)

# verify message stored encrypted
conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT body, is_encrypted FROM order_messages WHERE order_id = ?", (order_id,)).fetchone()
conn.close()
check("message is_encrypted=1", row[1] == 1)
check("message body looks like PGP", "BEGIN PGP MESSAGE" in row[0])

# buyer sends plaintext message
status, html, _ = buyer_get(f"/order/{order_ref}/messages")
token, answer = solve_captcha(html)
status, html, url = buyer_post(f"/order/{order_ref}/messages", {
    "body": "This is plaintext, visible to anyone with the link.",
    "pgp_mode": "plain",
    "captcha_token": token, "captcha_answer": answer
})
check("buyer sends plaintext message", status == 200)
check("message count = 2", message_count(order_id) == 2)

conn = sqlite3.connect("data/nodemarket.db")
rows = conn.execute("SELECT body, is_encrypted FROM order_messages WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
conn.close()
check("second message is_encrypted=0", rows[1][1] == 0)

# admin replies from admin panel
status, html, _ = admin_post(f"/admin/orders/{order_ref}/messages", {"body": "Shipping tomorrow, tracking #123"})
check("admin reply POST", status == 200)  # follows redirect to admin order page
check("message count = 3", message_count(order_id) == 3)

conn = sqlite3.connect("data/nodemarket.db")
rows = conn.execute("SELECT author, body, is_encrypted FROM order_messages WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
conn.close()
check("admin message author=seller", rows[2][0] == "seller")
check("admin message is_encrypted=0", rows[2][2] == 0)

# buyer sees all messages including seller reply
status, html, _ = buyer_get(f"/order/{order_ref}/messages")
check("buyer sees seller reply", "Shipping tomorrow" in html)
check("buyer sees encrypted message indicator", "PGP encrypted" in html)

# message captcha rate limit (wrong captcha)
status, html, _ = buyer_get(f"/order/{order_ref}/messages")
token, answer = solve_captcha(html)
status, html, url = buyer_post(f"/order/{order_ref}/messages", {
    "body": "This should fail captcha",
    "pgp_mode": "plain",
    "captcha_token": token, "captcha_answer": "0"
})
check("wrong captcha -> 400", status == 400)
check("message count unchanged", message_count(order_id) == 3)

# empty body rejection
status, html, _ = buyer_get(f"/order/{order_ref}/messages")
token, answer = solve_captcha(html)
status, html, url = buyer_post(f"/order/{order_ref}/messages", {
    "body": "",
    "pgp_mode": "plain",
    "captcha_token": token, "captcha_answer": answer
})
check("empty body -> 400", status == 400)


# ============================================================
# 2. PRODUCT REPORTING
# ============================================================

# seed another product
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("INSERT INTO products (name, description, price_cents) "
             "VALUES ('Another Product', 'Description', 500)")
conn.commit()
conn.close()

# GET report page
status, html, _ = buyer_get("/product/2/report")
check("report page loads", status == 200 and "Another Product" in html)

# submit valid report
status, html, _ = buyer_get("/product/2/report")
token, answer = solve_captcha(html)
status, html, _ = buyer_post("/product/2/report", {
    "reason": "scam", "description": "This looks like a scam.",
    "captcha_token": token, "captcha_answer": answer
})
check("valid report submitted", "Report submitted" in html)

# verify in DB
conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT reason, description, status FROM reports WHERE product_id = 2").fetchone()
conn.close()
check("report stored", row is not None and row[0] == "scam" and row[2] == "open")

# get an active product for reporting tests
conn = sqlite3.connect("data/nodemarket.db")
active_prod = conn.execute("SELECT id FROM products WHERE active = 1 LIMIT 1").fetchone()
conn.close()
report_pid = str(active_prod[0]) if active_prod else "1"

# report with wrong captcha
status, html, _ = buyer_get(f"/product/{report_pid}/report")
token, answer = solve_captcha(html)
status, html, _ = buyer_post(f"/product/{report_pid}/report", {
    "reason": "spam", "description": "spam",
    "captcha_token": token, "captcha_answer": "0"
})
print(f"DEBUG: wrong captcha report status={status}")
check("wrong captcha on report -> 400", status == 400)

# report with missing reason
status, html, _ = buyer_get(f"/product/{report_pid}/report")
token, answer = solve_captcha(html)
status, html, _ = buyer_post(f"/product/{report_pid}/report", {
    "reason": "", "description": "no reason",
    "captcha_token": token, "captcha_answer": answer
})
check("missing reason -> 400", status == 400)


# ============================================================
# 3. ADMIN REPORTS MODERATION
# ============================================================

# admin views reports
status, html, _ = get("/admin/reports")
check("admin reports page", status == 200 and "scam" in html)

# admin archives report
conn = sqlite3.connect("data/nodemarket.db")
rid = conn.execute(f"SELECT id FROM reports WHERE product_id = {report_pid}").fetchone()[0]
conn.close()

status, html, _ = admin_post(f"/admin/reports/{rid}/archive", {})
check("archive report -> 200 (follows redirect)", status == 200)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT status FROM reports WHERE id = ?", (rid,)).fetchone()
conn.close()
check("report status = archived", row[0] == "archived")

# admin action (deactivate product)
status, html, _ = admin_post(f"/admin/reports/{rid}/action", {})
check("action report -> 200 (follows redirect)", status == 200)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT status FROM reports WHERE id = ?", (rid,)).fetchone()
prod = conn.execute(f"SELECT active FROM products WHERE id = {report_pid}").fetchone()
conn.close()
check("report status = actioned", row[0] == "actioned")
check("product deactivated", prod[0] == 0)


# ============================================================
# 4. REGRESSION: order page links to messages
# ============================================================

status, html, _ = buyer_get(f"/order/{order_ref}")
check("order page has messages link", "/messages" in html)


# ============================================================
# 5. REGRESSION: product page has report link
# ============================================================

status, html, _ = buyer_get("/product/1")
check("product page has report link", "/product/1/report" in html and "Report listing" in html)


print()
failed = [n for n, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)