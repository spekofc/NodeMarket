"""v0.4 suite: categories CRUD, storefront category filter + text search,
BYO PGP checkout, plaintext-mode fail-closed regression.

Run with the server already up on 127.0.0.1:8000 and a FRESH database.
Stdlib only.
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


# --- crypto helpers (in-process) ------------------------------------------------

sys.path.insert(0, ".")
from app import pgp_compat  # noqa: E402,F401
from app.pgp import encrypt_for_store, validate_pgp_message  # noqa: E402
from pgpy import PGPKey, PGPUID, PGPMessage  # noqa: E402
from pgpy.constants import (PubKeyAlgorithm, KeyFlags, HashAlgorithm,  # noqa: E402
                            SymmetricKeyAlgorithm, CompressionAlgorithm)


def make_key(name):
    key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    key.add_uid(PGPUID.new(name),
                usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
                hashes=[HashAlgorithm.SHA256],
                ciphers=[SymmetricKeyAlgorithm.AES256],
                compression=[CompressionAlgorithm.ZLIB])
    return key


buyer_key = make_key("Buyer <buyer@test.local>")
BUYER_PUB = str(buyer_key.pubkey)
MARKER = "Shopper Street 77, Basement Flat, Torville"

# BYO: buyer encrypts their own delivery details with their OWN key
buyer_msg = PGPMessage.new(MARKER)
BYO_BLOCK = str(buyer_key.pubkey.encrypt(buyer_msg))

# validator unit checks
ok, _ = validate_pgp_message(BYO_BLOCK)
check("validate_pgp_message accepts encrypted block", ok)
ok, _ = validate_pgp_message("just some typed text")
check("validate_pgp_message rejects plaintext", not ok)
ok, _ = validate_pgp_message("-----BEGIN GARBAGE-----")
check("validate_pgp_message rejects garbage armor", not ok)

# signed-only (parseable, NOT encrypted) must be rejected
sign_key = PGPKey.new(PubKeyAlgorithm.RSASign, 2048)
sign_key.add_uid(PGPUID.new("S <s@test.local>"), usage={KeyFlags.Sign},
                 hashes=[HashAlgorithm.SHA256], ciphers=[SymmetricKeyAlgorithm.AES256],
                 compression=[CompressionAlgorithm.ZLIB])
# sign returns a PGPMessage containing the signature
signed_msg = sign_key.sign(PGPMessage.new(MARKER))
# now we need just the signed data (not encrypted). signed_msg is a message object
# that contains the literal + signature. Convert to armor string.
signed_only = str(signed_msg)
ok, _ = validate_pgp_message(signed_only)
check("validate_pgp_message rejects signed-only block", not ok)

# --- sessions ---------------------------------------------------------------

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
buyer = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

status, html, _ = get("/admin/login")
token, answer = solve_captcha(html)
status, html, _ = admin_post("/admin/login", {"captcha_token": token,
                                              "captcha_answer": answer,
                                              "password": "changeme-admin"})
check("admin login", status == 200)


def save_settings():
    """Post the FULL settings form (omitted fields wipe DB values)."""
    return admin_post("/admin/settings", {
        "store_name": "NodeMarket Store",
        "settlement_mode": "direct",
        "demo_enabled": "on",
        "pgp_public_key": BUYER_PUB,  # any valid key; used for store-key mode
    })


def place_order(method="demo", extra=None, wrong_captcha=False):
    data = {"payment_method": method}
    data.update(extra or {})
    # Use a valid active product
    conn = sqlite3.connect("data/nodemarket.db")
    prod = conn.execute("SELECT id FROM products WHERE active = 1 LIMIT 1").fetchone()
    conn.close()
    pid = str(prod[0]) if prod else "1"
    buyer_post("/cart/add", {"pid": pid, "qty": "1"})
    status, html, _ = buyer_get("/checkout")
    token, answer = solve_captcha(html)
    data["captcha_token"] = token or "x"
    data["captcha_answer"] = "0" if wrong_captcha else (answer or "0")
    return buyer_post("/checkout", data)


def order_count():
    conn = sqlite3.connect("data/nodemarket.db")
    n = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()
    return n


save_settings()

# seed products: 2 books-ish, 1 hardware-ish, with categories
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("INSERT INTO categories (name, slug) VALUES ('Books', 'books')")
conn.execute("INSERT INTO categories (name, slug) VALUES ('Hardware', 'hardware')")
conn.execute("INSERT INTO products (name, description, price_cents, category_id) "
             "VALUES ('Tor Guide Book', 'A deep guide about onion routing and privacy', 1500, 1)")
conn.execute("INSERT INTO products (name, description, price_cents, category_id) "
             "VALUES ('Raspberry Pi 5', 'Single board computer with 8GB RAM', 8000, 2)")
conn.execute("INSERT INTO products (name, description, price_cents, category_id) "
             "VALUES ('Privacy Zine', 'short zine about privacy', 300, 1)")
conn.commit()
conn.close()

# --- categories admin CRUD ---------------------------------------------------

status, html, _ = get("/admin/categories")
check("admin categories page lists categories",
      status == 200 and "Books" in html and "Hardware" in html)

status, html, _ = admin_post("/admin/categories/new", {"name": "Digital Goods"})
status, html, _ = get("/admin/categories")
check("category create works", "Digital Goods" in html)

conn = sqlite3.connect("data/nodemarket.db")
slug_dg = conn.execute("SELECT slug FROM categories WHERE name='Digital Goods'").fetchone()[0]
dg_id = conn.execute("SELECT id FROM categories WHERE name='Digital Goods'").fetchone()[0]
conn.close()
check("slug derived from name", slug_dg == "digital-goods", slug_dg)

# duplicate name -> slug suffix
admin_post("/admin/categories/new", {"name": "Digital Goods"})
conn = sqlite3.connect("data/nodemarket.db")
slug2 = conn.execute("SELECT slug FROM categories WHERE slug LIKE 'digital-goods-%'").fetchone()
conn.close()
check("duplicate slug gets -2 suffix", slug2 is not None and slug2[0] == "digital-goods-2",
      str(slug2))

# edit renames and re-slugs
status, html, _ = get(f"/admin/categories/{dg_id}/edit")
check("category edit form renders", status == 200 and "Digital Goods" in html)
admin_post(f"/admin/categories/{dg_id}/edit", {"name": "Digital Media"})
conn = sqlite3.connect("data/nodemarket.db")
nm = conn.execute("SELECT slug FROM categories WHERE name='Digital Media'").fetchone()
conn.close()
check("category edit updates slug", nm is not None and nm[0] == "digital-media", str(nm))

# delete a category: products must lose the FK, not the products themselves
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("UPDATE products SET category_id = ? WHERE id = 1", (dg_id,))
conn.commit()
conn.close()
admin_post(f"/admin/categories/{dg_id}/delete", {})
conn = sqlite3.connect("data/nodemarket.db")
cat_gone = conn.execute("SELECT COUNT(*) FROM categories WHERE id = ?", (dg_id,)).fetchone()[0]
p_alive = conn.execute("SELECT COUNT(*) FROM products WHERE id = 1 AND category_id IS NULL").fetchone()[0]
conn.close()
check("category delete removes category", cat_gone == 0)
check("category delete nullifies product FK, keeps product", p_alive == 1)

# product form has the category select
status, html, _ = get("/admin/products/new")
check("product form has category select",
      'name="category_id"' in html and "Books" in html and "Hardware" in html)

# assign category through the product form
admin_post("/admin/products/1/edit", {"name": "Tor Guide Book",
                                      "description": "A deep guide about onion routing and privacy",
                                      "price": "15.00", "active": "1", "category_id": "1"})

# --- storefront: category filter + search (buyer session) ---------------------

status, html, _ = buyer_get("/?category=books")
check("category filter shows book", "Tor Guide Book" in html)
check("category filter hides hardware", "Raspberry Pi 5" not in html)

status, html, _ = buyer_get("/?category=hardware")
check("hardware filter shows Pi", "Raspberry Pi 5" in html)

status, html, _ = buyer_get("/?category=does-not-exist")
check("unknown slug shows empty-state", "No products match this filter" in html)

status, html, _ = buyer_get("/?q=onion")
check("search by description term", "Tor Guide Book" in html and "Raspberry Pi 5" not in html)

status, html, _ = buyer_get("/?q=raspberry")
check("search by title term", "Raspberry Pi 5" in html and "Tor Guide Book" not in html)

status, html, _ = buyer_get("/?q=zzznothing")
check("search no-match empty state", "No products match this filter" in html)

status, html, _ = buyer_get("/?q=privacy&category=books")
check("combined search+filter", "Privacy Zine" in html and "Raspberry Pi 5" not in html)

status, html, _ = buyer_get("/?q=<script>")
check("search term not reflected raw", "<script>" not in html)

# get the Raspberry Pi 5 product ID dynamically
conn = sqlite3.connect("data/nodemarket.db")
pi_id = conn.execute("SELECT id FROM products WHERE name = 'Raspberry Pi 5'").fetchone()[0]
conn.close()

status, html, _ = buyer_get(f"/product/{pi_id}")
check("product page shows category badge", "Hardware" in html and 'category=' in html)
check("product page shows FULL description", "8GB RAM" in html)

# --- BYO PGP checkout ---------------------------------------------------------

# store key valid; buyer pre-encrypts with their own key
status, html, url = place_order(extra={"pgp_mode": "plain",
                                       "delivery_details": MARKER})
check("plain-mode order placed", status == 200 and "/order/" in url)
plain_ref = url.rsplit("/", 1)[-1]

status, html, url = place_order(extra={"pgp_mode": "own", "pgp_block": BYO_BLOCK,
                                       "delivery_details": ""})
check("BYO order placed", status == 200 and "/order/" in url)
byo_ref = url.rsplit("/", 1)[-1]

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT buyer_encrypted FROM orders WHERE order_ref = ?",
                   (byo_ref,)).fetchone()
conn.close()
check("BYO ciphertext stored verbatim", row is not None and row[0].strip() == BYO_BLOCK.strip())

# the BYO ciphertext must decrypt with the BUYER's key, not the store's
msg = PGPMessage()
msg.parse(row[0])
decrypted = buyer_key.decrypt(msg)
check("BYO ciphertext decrypts with buyer key", MARKER in str(decrypted.message))

# invalid BYO block: fail closed, no row
baseline = order_count()
status, html, _ = place_order(extra={"pgp_mode": "own", "pgp_block": "not a pgp block"})
check("invalid BYO -> 400", status == 400)
check("invalid BYO error message", "PGP" in html)
status, html, _ = place_order(extra={"pgp_mode": "own", "pgp_block": signed_only})
check("signed-only block -> 400", status == 400)
status, html, _ = place_order(extra={"pgp_mode": "own", "pgp_block": ""})
check("empty BYO block -> 400", status == 400)
check("failed BYO attempts created no rows", order_count() == baseline)

# plaintext never on disk
db_bytes = Path("data/nodemarket.db").read_bytes()
wal_bytes = Path("data/nodemarket.db-wal").read_bytes() \
    if Path("data/nodemarket.db-wal").exists() else b""
check("MARKER not in .db", MARKER.encode() not in db_bytes)
check("MARKER not in .db-wal", MARKER.encode() not in wal_bytes)

# store-key mode still fail-closed when key is garbage (regression)
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("UPDATE store_settings SET pgp_public_key = '-----BEGIN GARBAGE-----'")
conn.commit()
conn.close()
status, html, _ = place_order(extra={"pgp_mode": "plain", "delivery_details": MARKER})
check("plain mode fail-closed with bad store key", status == 400)
status, html, url = place_order(extra={"pgp_mode": "own", "pgp_block": BYO_BLOCK})
check("BYO mode works WITHOUT a valid store key",
      status == 200 and "/order/" in url)

print()
failed = [n for n, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
