"""v0.6 suite: vendor listing portal, seller token management, admin moderation.

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


# --- setup ---
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
buyer = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

status, html, _ = get("/admin/login")
token, answer = solve_captcha(html)
status, html, _ = admin_post("/admin/login", {"captcha_token": token,
                                              "captcha_answer": answer,
                                              "password": "changeme-admin"})
check("admin login", status == 200)

# seed 1 category
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("INSERT INTO categories (name, slug) VALUES ('Electronics', 'electronics')")
conn.commit()
conn.close()

# admin settings: enable moderated listings, set a valid PGP key
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
    "listing_policy": "moderated",
})


# ============================================================
# 1. SELL PAGE & SUBMISSION
# ============================================================

# GET /sell
status, html, _ = buyer_get("/sell")
check("sell page loads", status == 200 and "Sell / Post Listing" in html)

# submit listing with wrong captcha
status, html, _ = buyer_get("/sell")
token, answer = solve_captcha(html)
status, html, _ = buyer_post("/sell", {
    "name": "Test Item", "description": "Desc", "price": "100.00",
    "currency": "USD", "category_id": "1", "payout_address": "",
    "captcha_token": token, "captcha_answer": "0"
})
check("wrong captcha -> 400", status == 400)

# submit valid listing
status, html, _ = buyer_get("/sell")
token, answer = solve_captcha(html)
status, html, _ = buyer_post("/sell", {
    "name": "Raspberry Pi 5 8GB", "description": "Brand new, sealed box",
    "price": "120.00", "currency": "USD", "category_id": "1",
    "payout_address": "bc1qtest...", "captcha_token": token, "captcha_answer": answer
})
check("valid listing submitted", status == 200 and "Listing Posted" in html)
check("success page shows seller token", "seller_token" in html.lower() or "token" in html.lower())
print(f"DEBUG success page snippet: {html[:3000]}")

# extract seller_token from success page - try multiple patterns
m = re.search(r"(?:seller[_-]?token|token)[^a-f0-9]*([a-f0-9]{32})", html, re.I)
if not m:
    m = re.search(r"<code>([a-f0-9]{32})</code>", html)
if not m:
    m = re.search(r"token[^a-f0-9]*([a-f0-9]{32})", html, re.I)
if not m:
    m = re.search(r"([a-f0-9]{32})", html)
seller_token = m.group(1) if m else None
check("seller_token extracted", seller_token is not None, seller_token)

# listing should be in DB with pending_approval
conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT id, status, seller_token FROM seller_listings WHERE seller_token = ?",
                   (seller_token,)).fetchone()
conn.close()
check("listing in DB", row is not None)
check("listing status = pending_approval", row[1] == "pending_approval")
listing_id = row[0]


# ============================================================
# 2. SELLER MANAGEMENT VIA TOKEN
# ============================================================

# GET seller manage page
status, html, _ = buyer_get(f"/sell/manage/{seller_token}")
check("seller manage page loads", status == 200 and "Raspberry Pi 5 8GB" in html)
check("seller page shows token", seller_token[:8] in html)
check("seller page shows status pending", "Pending Approval" in html or "pending_approval" in html)

# pause/resume not allowed for pending_approval (only active/paused)
# but the button shouldn't show - verify no error


# ============================================================
# 3. ADMIN MODERATION
# ============================================================

# admin views listings
status, html, _ = get("/admin/listings")
check("admin listings page", status == 200 and "Raspberry Pi 5 8GB" in html)
check("admin shows pending status", "Pending" in html)

# admin approves
status, html, _ = admin_post(f"/admin/listings/{listing_id}/approve", {})
check("admin approve -> 200 (follows redirect)", status == 200)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT status FROM seller_listings WHERE id = ?", (listing_id,)).fetchone()
conn.close()
check("listing status = active", row[0] == "active")

# seller manage page now shows active
status, html, _ = buyer_get(f"/sell/manage/{seller_token}")
check("seller page shows active", "Active" in html)

# seller can pause
status, html, _ = buyer_post(f"/sell/manage/{seller_token}/pause", {})
check("seller pause -> 200 (follows redirect)", status == 200)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT status FROM seller_listings WHERE id = ?", (listing_id,)).fetchone()
conn.close()
check("listing status = paused", row[0] == "paused")

# admin can also pause
status, html, _ = admin_post(f"/admin/listings/{listing_id}/pause", {})
check("admin pause -> 200 (follows redirect)", status == 200)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT status FROM seller_listings WHERE id = ?", (listing_id,)).fetchone()
conn.close()
check("listing status = active (resumed by admin)", row[0] == "active")

# admin rejects a new listing
# submit another listing
status, html, _ = buyer_get("/sell")
token, answer = solve_captcha(html)
status, html, _ = buyer_post("/sell", {
    "name": "Another Item", "description": "Desc", "price": "50.00",
    "currency": "USD", "category_id": "1", "payout_address": "",
    "captcha_token": token, "captcha_answer": answer
})
m = re.search(r"(?:seller[_-]?token|token)[^a-f0-9]*([a-f0-9]{32})", html, re.I)
if not m:
    m = re.search(r"<code>([a-f0-9]{32})</code>", html)
if not m:
    m = re.search(r"token[^a-f0-9]*([a-f0-9]{32})", html, re.I)
if not m:
    m = re.search(r"([a-f0-9]{32})", html)
seller_token2 = m.group(1) if m else None
check("second listing submitted", seller_token2 is not None, seller_token2)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT id FROM seller_listings WHERE seller_token = ?", (seller_token2,)).fetchone()
conn.close()
listing_id2 = row[0]

status, html, _ = admin_post(f"/admin/listings/{listing_id2}/reject", {})
check("admin reject -> 200 (follows redirect)", status == 200)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT status FROM seller_listings WHERE id = ?", (listing_id2,)).fetchone()
conn.close()
check("listing status = rejected", row[0] == "rejected")


# ============================================================
# 4. POLICY MODES
# ============================================================

# test disabled policy
admin_post("/admin/settings", {
    "store_name": "NodeMarket Store",
    "settlement_mode": "direct",
    "demo_enabled": "on",
    "pgp_public_key": STORE_PUB,
    "listing_policy": "disabled",
})

status, html, _ = buyer_get("/sell")
check("disabled policy -> 403", status == 403)

# test open policy
admin_post("/admin/settings", {
    "store_name": "NodeMarket Store",
    "settlement_mode": "direct",
    "demo_enabled": "on",
    "pgp_public_key": STORE_PUB,
    "listing_policy": "open",
})

status, html, _ = buyer_get("/sell")
token, answer = solve_captcha(html)
status, html, _ = buyer_post("/sell", {
    "name": "Open Policy Item", "description": "Auto-published", "price": "10.00",
    "currency": "USD", "category_id": "1", "payout_address": "",
    "captcha_token": token, "captcha_answer": answer
})
check("open policy -> active immediately", status == 200)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT status FROM seller_listings WHERE name = 'Open Policy Item'").fetchone()
conn.close()
check("open policy listing status = active", row[0] == "active")


# ============================================================
# 5. CATALOG INTEGRATION
# ============================================================

# restore moderated policy
admin_post("/admin/settings", {
    "store_name": "NodeMarket Store",
    "settlement_mode": "direct",
    "demo_enabled": "on",
    "pgp_public_key": STORE_PUB,
    "listing_policy": "moderated",
})

# approved listing should appear in catalog
status, html, _ = buyer_get("/")
check("approved listing in catalog", "Raspberry Pi 5 8GB" in html)

# rejected listing should NOT appear
check("rejected listing not in catalog", "Another Item" not in html)

# pending listing should NOT appear
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("INSERT INTO seller_listings (seller_token, name, description, price_cents, currency, status) "
             "VALUES ('tokentest12345678901234', 'Pending Item', 'desc', 1000, 'USD', 'pending_approval')")
conn.commit()
conn.close()

status, html, _ = buyer_get("/")
check("pending listing not in catalog", "Pending Item" not in html)


# ============================================================
# 6. REGRESSION: NAV LINKS
# ============================================================

status, html, _ = buyer_get("/")
check("header has Sell link", "/sell" in html and "Sell / Post Listing" in html)

status, html, _ = get("/admin")
check("admin nav has Listings link", "/admin/listings" in html and "Listings" in html)

# product detail shows report link still
status, html, _ = buyer_get("/")
m = re.search(r'/product/(\d+)', html)
if m:
    pid = m.group(1)
    status, html, _ = buyer_get(f"/product/{pid}")
    check("product page has report link", f"/product/{pid}/report" in html and "Report listing" in html)
else:
    check("product page has report link", False, "no product found in catalog")


print()
failed = [n for n, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)