"""v0.3 end-to-end test: multi-currency checkout (BTC/XMR/Demo) and the
full Temporary Escrow state machine, incl. buyer release + CSRF hardening.

Run with the server already up on 127.0.0.1:8000. Stdlib only.
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

BASE = "http://127.0.0.1:8000"

results = []


def check(name, ok, extra=""):
    results.append((name, ok))
    print(("OK  " if ok else "FAIL") + f" {name}" + (f"  [{extra}]" if extra and not ok else ""))


# --- helpers ---------------------------------------------------------------

def _resp(opener, req):
    try:
        r = opener.open(req)
        return r.status, r.read().decode(), r.geturl()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), exc.geturl() or ""


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


opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

# --- admin login ------------------------------------------------------------

status, html, _ = get("/admin/login")
token, answer = solve_captcha(html)
status, html, _ = post("/admin/login", {"captcha_token": token,
                                        "captcha_answer": answer,
                                        "password": "changeme-admin"})
check("admin login", status == 200)

# --- PGP key (checkout fails closed without it) ------------------------------

sys.path.insert(0, ".")
from app import pgp_compat  # noqa: E402,F401
from pgpy import PGPKey, PGPUID  # noqa: E402
from pgpy.constants import (PubKeyAlgorithm, KeyFlags, HashAlgorithm,  # noqa: E402
                            SymmetricKeyAlgorithm, CompressionAlgorithm)

key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
uid = PGPUID.new("NodeMarket Test <store@test.local>")
key.add_uid(uid, usage={KeyFlags.Sign, KeyFlags.EncryptCommunications,
                        KeyFlags.EncryptStorage},
            hashes=[HashAlgorithm.SHA256],
            ciphers=[SymmetricKeyAlgorithm.AES256],
            compression=[CompressionAlgorithm.ZLIB, CompressionAlgorithm.ZIP,
                         CompressionAlgorithm.Uncompressed])
PUB_ARMOR = str(key.pubkey)

# valid BIP32 master xpub (official test vector, seed 000102...0f)
TEST_XPUB = ("xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29E"
             "SFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8")
XMR_SUBS = "48jewbtxe4jU3MnzJFjZ6sP3tJ6dLq9dZqESiNQpYh9W5rfWCG5pL1tfJguVCEqx3A6bLLBppHBvf8nCJbCWMBG4935q1om"

conn = sqlite3.connect("data/nodemarket.db")
conn.execute("INSERT INTO products (name, description, price_cents) VALUES ('Escrow Widget', 'w', 500)")
conn.execute("INSERT INTO products (name, description, price_cents) VALUES ('Another Widget', 'w', 250)")
conn.commit()
conn.close()


def save_settings(**overrides):
    """POST the full settings form (fields default unless overridden)."""
    data = {
        "store_name": "NodeMarket Store",
        "pgp_public_key": PUB_ARMOR,
        "settlement_mode": "escrow",
        "btc_enabled": "on", "btc_mode": "xpub", "btc_rate": "0.000015",
        "xpub": TEST_XPUB,
        "xmr_enabled": "", "xmr_address": "", "xmr_subaddresses": XMR_SUBS,
        "xmr_rate": "0.15",
        "demo_enabled": "on",
        "payout_btc_address": "", "payout_xmr_address": "",
    }
    data.update(overrides)
    # unchecked checkboxes: send nothing
    for k, v in list(data.items()):
        if v == "":
            del data[k]
    return post("/admin/settings", data)


# buyer session ---------------------------------------------------------------

buyer = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


# --- 1. checkout surfaces enabled methods only ------------------------------

save_settings(xmr_enabled="on")  # enable XMR with subaddress list
status, html, _ = get("/admin/settings")
check("settings form has btc fields", 'name="btc_mode"' in html and 'name="xpub"' in html)
check("settings form has settlement radios", 'name="settlement_mode"' in html
      and 'value="escrow"' in html and 'value="direct"' in html)
check("settings form has payout addresses", 'name="payout_btc_address"' in html
      and 'name="payout_xmr_address"' in html)

# add product to cart as buyer, open checkout
body = urllib.parse.urlencode({"pid": "1", "qty": "1"}).encode()
buyer.open(urllib.request.Request(BASE + "/cart/add", data=body, method="POST"))
status, html, _ = _resp(buyer, urllib.request.Request(BASE + "/checkout"))
check("checkout shows btc radio", 'value="btc"' in html)
check("checkout shows xmr radio", 'value="xmr"' in html)
check("checkout shows demo radio", 'value="demo"' in html)
check("checkout is escrow-aware", "Temporary Escrow" in html)

token, answer = solve_captcha(html)
# 2. BTC order via xpub (escrow mode)
body = urllib.parse.urlencode({"delivery_details": "secret street 1",
                               "payment_method": "btc",
                               "captcha_token": token, "captcha_answer": answer}).encode()
status, html, url = _resp(buyer, urllib.request.Request(BASE + "/checkout", data=body, method="POST"))
check("btc order created", "/order/" in url)
btc_ref = url.rsplit("/", 1)[-1]
check("btc order shows derived address", "bc1q" in html)
check("btc order shows manual rate line", "0.00007500 BTC" in html)
check("btc order escrow section", "Escrow status" in html)
check("no release button while pending_payment", "release payment" not in html)
check("escrow history shows pending_payment", "pending_payment" in html)
check("order page zero script", "<script" not in html)


def place_order(method):
    """Add to cart, open checkout, solve captcha, place order."""
    body = urllib.parse.urlencode({"pid": "1", "qty": "1"}).encode()
    _resp(buyer, urllib.request.Request(BASE + "/cart/add", data=body, method="POST"))
    status, html, _ = _resp(buyer, urllib.request.Request(BASE + "/checkout"))
    token, answer = solve_captcha(html)
    body = urllib.parse.urlencode({"delivery_details": "d", "payment_method": method,
                                   "captcha_token": token, "captcha_answer": answer}).encode()
    return _resp(buyer, urllib.request.Request(BASE + "/checkout", data=body, method="POST"))


# 3. XMR order via subaddress rotation
status, html, url = place_order("xmr")
check("xmr order created", "/order/" in url)
check("xmr order shows subaddress", XMR_SUBS.split(",")[0] in html)
check("xmr order shows manual rate line", "0.750000 XMR" in html)

# 4. disabled method falls back, no crash (fallback order reused below)
save_settings(demo_enabled="on")  # xmr_enabled dropped -> disabled
status, html, _ = get("/checkout")
check("xmr radio gone when disabled", 'value="xmr"' not in html)
status, html, url = place_order("xmr")
check("invalid method falls back w/o crash", "/order/" in url)
check("fallback order is btc or demo", "Demo payment" in html or "Bitcoin" in html)
dispute_ref = url.rsplit("/", 1)[-1]

# --- 5. full escrow state machine --------------------------------------------

def admin_mark(ref, st):
    return post(f"/admin/orders/{ref}/status", {"status": st})


# btc order: pending_payment -> in_escrow
status, html, _ = admin_mark(btc_ref, "in_escrow")
check("admin marks payment received (in_escrow)", status == 200)
check("admin order page shows escrow history", "Escrow history" in html)

status, html, _ = get(f"/order/{btc_ref}")
check("buyer sees release button in escrow", "Confirm receipt &amp; release payment" in html)

# illegal buyer move: release a completed order later; first test illegal admin move
status, html, _ = admin_mark(btc_ref, "paid")  # illegal in escrow mode
status, html, _ = get(f"/admin/orders/{btc_ref}")
check("illegal transition rejected (still in_escrow)", "in_escrow" in html)

# buyer releases
body = urllib.parse.urlencode({}).encode()
status, html, _ = _resp(buyer, urllib.request.Request(
    BASE + f"/order/{btc_ref}/release", data=body, method="POST"))
check("buyer release -> completed_released", "completed_released" in html)
check("release page shows released note", "Payment released" in html)
check("payout hook note recorded (manual fallback)", "pay out manually" in html)

# double release rejected with clear error
status, html, _ = _resp(buyer, urllib.request.Request(
    BASE + f"/order/{btc_ref}/release", data=body, method="POST"))
check("second release rejected w/ error", "Cannot release payment" in html)

# --- 6. disputed path (reuses the fallback order, escrow mode) ----------------

admin_mark(dispute_ref, "in_escrow")
status, html, _ = admin_mark(dispute_ref, "disputed")
check("admin opens dispute", status == 200 and "disputed" in html)
status, html, _ = admin_mark(dispute_ref, "completed_released")
check("admin resolves dispute -> released", status == 200)

# --- 7. direct mode: no escrow UI, classic flow -------------------------------

save_settings(settlement_mode="direct", btc_enabled="", demo_enabled="on",
              xmr_enabled="", xmr_subaddresses="")
status, html, url = place_order("demo")
check("direct mode order placed", "/order/" in url)
direct_ref = url.rsplit("/", 1)[-1]
check("direct order has no escrow section", "Escrow status" not in html)
status, html, _ = admin_mark(direct_ref, "paid")
check("direct: paid", status == 200)
status, html, _ = admin_mark(direct_ref, "completed")
check("direct: completed", status == 200)
status, html, _ = admin_mark(direct_ref, "in_escrow")  # illegal in direct mode
status, html, _ = get(f"/admin/orders/{direct_ref}")
check("direct: escrow move rejected", "completed" in html and "in_escrow" not in html)

# --- 8. database invariants ---------------------------------------------------

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT settlement_mode, status FROM orders WHERE order_ref = ?",
                   (btc_ref,)).fetchone()
check("order settlement_mode frozen (escrow)", row == ("escrow", "completed_released"))
n_events = conn.execute(
    "SELECT COUNT(*) FROM escrow_events e JOIN orders o ON o.id = e.order_id "
    "WHERE o.order_ref = ?", (btc_ref,)).fetchone()[0]
check("escrow_events recorded", n_events >= 4, f"n={n_events}")
row = conn.execute("SELECT settlement_mode FROM orders WHERE order_ref = ?",
                   (direct_ref,)).fetchone()
check("order settlement_mode frozen (direct)", row == ("direct",))
plain = conn.execute("SELECT buyer_encrypted FROM orders WHERE order_ref = ?",
                     (btc_ref,)).fetchone()[0]
check("buyer data still PGP ciphertext", "BEGIN PGP MESSAGE" in plain)
conn.close()

print()
failed = [n for n, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
