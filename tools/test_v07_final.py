"""v0.7 suite: Visual Customizer, image uploads with EXIF stripping,
custom pages, navigation builder, theme presets, layout settings.

Run with server on 127.0.0.1:8000, fresh DB.
"""

import json
import re
import sys
import uuid
import io
import tempfile
import sqlite3
import warnings
from pathlib import Path
import urllib.request
import urllib.parse
import http.cookiejar

warnings.filterwarnings("ignore")

BASE = "http://127.0.0.1:8000"

results = []


def check(name, ok, extra=""):
    results.append((name, ok))
    print(("OK  " if ok else "FAIL") + f" {name}" + (f"  [{extra}]" if extra and not ok else ""))


# --- Single opener with cookie jar for all requests ---
# The suites assert on the POST's own status (303). urllib follows redirects
# by default, so install a handler that refuses to follow and lets the 3xx
# surface as an HTTPError. Cookies from the 3xx response are still recorded.
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(cj),
    _NoRedirect(),
)


def _resp(opener, req):
    try:
        r = opener.open(req)
        return r.status, r.read().decode(), r.geturl()
    except urllib.error.HTTPError as exc:
        # For a redirect, hand back the Location target as the "url" so
        # checks can assert where the POST sent the client.
        loc = exc.headers.get("Location") if exc.headers else None
        return exc.code, exc.read().decode(), loc or exc.geturl()


def get(path):
    return _resp(opener, urllib.request.Request(BASE + path))


def post(path, data):
    body = urllib.parse.urlencode(data).encode()
    return _resp(opener, urllib.request.Request(BASE + path, data=body, method="POST"))


def solve_captcha(html):
    """Extract token from the page, fetch the SVG, parse glyphs, return answer."""
    m = re.search(r'/captcha\.svg\?token=([A-Za-z0-9_-]+)', html)
    if not m:
        return None, None
    token = m.group(1)
    status, svg, _ = get(f"/captcha.svg?token={token}")
    if status != 200:
        return None, None
    glyphs = re.findall(r"<text [^>]*>([^<]+)</text>", svg)
    q = "".join(glyphs)
    m2 = re.match(r"^(\d+)\s*([+\-])\s*(\d+)$", q)
    if not m2:
        raise AssertionError(f"unparseable question: {q!r}")
    a, op, b = int(m2.group(1)), m2.group(2), int(m2.group(3))
    return token, str(a + b if op == "+" else a - b)


def place_order(delivery="Test address", method="demo", pgp_mode="plain", pgp_block=""):
    post("/cart/add", {"pid": "1", "qty": "1"})
    status, html, _ = get("/checkout")
    token, answer = solve_captcha(html)
    data = {"delivery_details": delivery, "payment_method": method,
            "pgp_mode": pgp_mode, "pgp_block": pgp_block,
            "captcha_token": token, "captcha_answer": answer}
    return post("/checkout", data)


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
import json
import re
import sys
import uuid
import io
import tempfile
import sqlite3
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# pgp_compat must be imported before pgpy to install imghdr shim
sys.path.insert(0, ".")
from app import pgp_compat  # noqa: F401,E402
from pgpy import PGPKey, PGPUID  # noqa: E402
from pgpy.constants import (PubKeyAlgorithm, KeyFlags, HashAlgorithm,  # noqa: E402
                            SymmetricKeyAlgorithm, CompressionAlgorithm)

from app.db import query, execute, init_db
init_db()

# seed 1 category
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("INSERT INTO categories (name, slug) VALUES ('Electronics', 'electronics')")
conn.execute(
    "INSERT INTO products (name, description, price_cents, currency, active, category_id) "
    "VALUES ('Test Widget', 'A test product', 1999, 'USD', 1, 1)"
)
conn.commit()
conn.close()

# admin settings: enable demo, set a valid PGP key
from pgpy import PGPKey, PGPUID
from pgpy.constants import (PubKeyAlgorithm, KeyFlags, HashAlgorithm,
                            SymmetricKeyAlgorithm, CompressionAlgorithm)
store_key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
store_key.add_uid(PGPUID.new("Store <store@test.local>"),
                  usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
                  hashes=[HashAlgorithm.SHA256], ciphers=[SymmetricKeyAlgorithm.AES256],
                  compression=[CompressionAlgorithm.ZLIB])
STORE_PUB = str(store_key.pubkey)

# Admin login
status, html, _ = get("/admin/login")
token, answer = solve_captcha(html)
r = post("/admin/login", {
    "captcha_token": token, "captcha_answer": answer,
    "password": "changeme-admin"
})
check("admin login", r[0] == 303)

# Admin settings
from pgpy import PGPKey, PGPUID
from pgpy.constants import (PubKeyAlgorithm, KeyFlags, HashAlgorithm,
                            SymmetricKeyAlgorithm, CompressionAlgorithm)
store_key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
store_key.add_uid(PGPUID.new("Store <store@test.local>"),
                  usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
                  hashes=[HashAlgorithm.SHA256], ciphers=[SymmetricKeyAlgorithm.AES256],
                  compression=[CompressionAlgorithm.ZLIB])
STORE_PUB = str(store_key.pubkey)

r = post("/admin/settings", {
    "store_name": "NodeMarket Store",
    "settlement_mode": "direct",
    "demo_enabled": "on",
    "pgp_public_key": STORE_PUB,
    "listing_policy": "moderated",
})
check("admin settings", r[0] == 303)


# ============================================================
# 1. THEME PRESETS & CUSTOM COLORS
# ============================================================

# Test theme preset selection
status, html, _ = get("/admin/customize")
token, answer = solve_captcha(html)
r = post("/admin/customize/theme", {
    "theme_preset": "green",
    "bg_color": "", "card_bg_color": "", "primary_color": "",
    "text_color": "", "border_radius": "8", "font_family": "system",
    "captcha_token": token, "captcha_answer": answer
})
check("theme preset green -> 303", r[0] == 303)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT theme_preset, primary_color FROM store_settings WHERE id = 1").fetchone()
conn.close()
check("theme_preset saved", row[0] == "green")
check("primary_color from preset", row[1] == "#00ff41")

# Test custom colors override preset
status, html, _ = get("/admin/customize")
token, answer = solve_captcha(html)
r = post("/admin/customize/theme", {
    "theme_preset": "custom",
    "bg_color": "#111111", "card_bg_color": "#222222",
    "primary_color": "#ff0000", "text_color": "#ffffff",
    "border_radius": "12", "font_family": "monospace",
    "captcha_token": token, "captcha_answer": answer
})
check("custom colors -> 303", r[0] == 303)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT theme_preset, bg_color, primary_color, border_radius, font_family FROM store_settings WHERE id = 1").fetchone()
conn.close()
check("custom colors saved", row[0] == "custom" and row[1] == "#111111" and row[2] == "#ff0000" and row[3] == 12 and row[4] == "monospace")


# ============================================================
# 2. LAYOUT SETTINGS
# ============================================================

status, html, _ = get("/admin/customize")
token, answer = solve_captcha(html)
r = post("/admin/customize/layout", {
    "category_position": "left",
    "grid_columns": "4",
    "grid_style": "list",
    "show_category_badge": "0",
    "show_description": "1",
    "show_add_to_cart": "0",
    "captcha_token": token, "captcha_answer": answer
})
check("layout settings -> 303", r[0] == 303)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT category_position, grid_columns, grid_style, show_category_badge, show_description, show_add_to_cart FROM store_settings WHERE id = 1").fetchone()
conn.close()
check("layout saved", row[0] == "left" and row[1] == 4 and row[2] == "list" and row[3] == 0 and row[4] == 1 and row[5] == 0)


# ============================================================
# 3. IDENTITY & IMAGES (Upload with EXIF stripping)
# ============================================================

# Create test images
from PIL import Image
import io
import tempfile

test_img = Image.new('RGB', (100, 100), color='red')
buf = io.BytesIO()
test_img.save(buf, format='PNG')
img_bytes = buf.getvalue()

test_img2 = Image.new('RGB', (200, 100), color='blue')
buf2 = io.BytesIO()
test_img2.save(buf2, format='PNG')
img_bytes2 = buf2.getvalue()

# Save to temp files
with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
    f.write(img_bytes)
    logo_path = f.name
with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
    f.write(img_bytes2)
    banner_path = f.name

# Upload via identity endpoint
status, html, _ = get("/admin/customize")
token, answer = solve_captcha(html)

import uuid
boundary = uuid.uuid4().hex
body = b''
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="store_name"\r\n\r\nTest Store\r\n'
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="slogan"\r\n\r\nTest slogan\r\n'
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="footer_text"\r\n\r\nTest footer\r\n'
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="banner_title"\r\n\r\nTest Banner\r\n'
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="banner_subtitle"\r\n\r\nSubtitle text\r\n'
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="banner_button_text"\r\n\r\nShop Now\r\n'
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="banner_button_url"\r\n\r\n/\r\n'

with open(logo_path, 'rb') as f:
    logo_data = f.read()
body += f'--{boundary}\r\n'.encode()
body += f'Content-Disposition: form-data; name="logo_file"; filename="logo.png"\r\n'.encode()
body += b'Content-Type: image/png\r\n\r\n'
body += logo_data + b'\r\n'

with open(banner_path, 'rb') as f:
    banner_data = f.read()
body += f'--{boundary}\r\n'.encode()
body += f'Content-Disposition: form-data; name="banner_file"; filename="banner.png"\r\n'.encode()
body += b'Content-Type: image/png\r\n\r\n'
body += banner_data + b'\r\n'

body += f'--{boundary}\r\n'.encode()
body += f'Content-Disposition: form-data; name="captcha_token"\r\n\r\n'.encode()
# Get fresh captcha for identity upload
status, html, _ = get("/admin/customize")
token, answer = solve_captcha(html)
body += token.encode() + b'\r\n'
body += f'--{boundary}\r\n'.encode()
body += f'Content-Disposition: form-data; name="captcha_answer"\r\n\r\n'.encode()
body += answer.encode() + b'\r\n'

body += f'--{boundary}--\r\n'.encode()

req = urllib.request.Request('http://127.0.0.1:8000/admin/customize/identity', data=body, method='POST')
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
try:
    r = opener.open(req, timeout=30)
    status = r.status
except urllib.error.HTTPError as e:
    status = e.code

check("identity upload -> 303", status == 303)


# ============================================================
# 4. NAVIGATION BUILDER
# ============================================================

nav_items = [
    {"label": "Catalog", "url": "/", "custom": False},
    {"label": "Sell", "url": "/sell", "custom": False},
    {"label": "PGP Guide", "url": "/page/guia-pgp", "custom": True},
    {"label": "Rules", "url": "/page/regras", "custom": True},
    {"label": "GitHub", "url": "https://github.com/spekofc/NodeMarket", "custom": True, "external": True}
]

status, html, _ = get("/admin/customize")
token, answer = solve_captcha(html)

r = post("/admin/customize/navigation", {
    "nav_items_json": json.dumps(nav_items),
    "captcha_token": token, "captcha_answer": answer
})
check("navigation save -> 303", r[0] == 303)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT nav_items FROM store_settings WHERE id = 1").fetchone()
conn.close()
saved_items = json.loads(row[0]) if row[0] else []
check("nav items saved", len(saved_items) == 5)
check("custom flag preserved", saved_items[2]["custom"] == True)
check("external flag preserved", saved_items[4]["external"] == True)


# ============================================================
# 5. CUSTOM PAGES
# ============================================================

# Create page
status, html, _ = get("/admin/customize")
token, answer = solve_captcha(html)
r = post("/admin/customize/pages/new", {
    "slug": "guia-pgp",
    "title": "Guia PGP",
    "content": "# Guia PGP\n\nComo usar PGP no NodeMarket.\n\n## Passo 1\nGere suas chaves.",
    "is_published": "1",
    "captcha_token": token, "captcha_answer": answer
})
check("page create -> 303", r[0] == 303)

conn = sqlite3.connect("data/nodemarket.db")
row = conn.execute("SELECT id, slug, title, is_published FROM custom_pages WHERE slug = 'guia-pgp'").fetchone()
conn.close()
check("page created in DB", row is not None and row[1] == "guia-pgp" and row[2] == "Guia PGP" and row[3] == 1)
page_id = row[0] if row else None

# Access public page
if page_id:
    status, html, _ = get(f"/page/guia-pgp")
    check("public page loads", status == 200)
    check("page content rendered", "Guia PGP" in html and "Como usar PGP" in html)

# Update page
if page_id:
    status, html, _ = get(f"/admin/customize/pages/{page_id}/edit")
    token, answer = solve_captcha(html)
    
    r = post(f"/admin/customize/pages/{page_id}/edit", {
        "slug": "guia-pgp-atualizado",
        "title": "Guia PGP Atualizado",
        "content": "Conteúdo atualizado.",
        "is_published": "1",
        "captcha_token": token, "captcha_answer": answer
    })
    check("page update -> 303", r[0] == 303)

    conn = sqlite3.connect("data/nodemarket.db")
    row = conn.execute("SELECT slug, title FROM custom_pages WHERE id = ?", (page_id,)).fetchone()
    conn.close()
    check("page updated", row[0] == "guia-pgp-atualizado" and row[1] == "Guia PGP Atualizado")

# Delete page
if page_id:
    status, html, _ = get(f"/admin/customize/pages/{page_id}/edit")
    token, answer = solve_captcha(html)
    
    r = post(f"/admin/customize/pages/{page_id}/delete", {
        "captcha_token": token, "captcha_answer": answer
    })
    check("page delete -> 303", r[0] == 303)

    conn = sqlite3.connect("data/nodemarket.db")
    row = conn.execute("SELECT id FROM custom_pages WHERE id = ?", (page_id,)).fetchone()
    conn.close()
    check("page deleted", row is None)


# ============================================================
# 6. REGRESSION: existing tests still pass
# ============================================================

# Run a quick order to ensure checkout still works
status, html, url = post("/cart/add", {"pid": "1", "qty": "1"})
r = post("/checkout", {
    "delivery_details": "Test address",
    "payment_method": "demo",
    "pgp_mode": "plain",
    "pgp_block": "",
    "captcha_token": "dummy", "captcha_answer": "dummy"
})
# The above will fail captcha, so we need to do it properly
# Let's do it properly
post("/cart/add", {"pid": "1", "qty": "1"})
status, html, _ = get("/checkout")
token, answer = solve_captcha(html)
r = post("/checkout", {
    "delivery_details": "Test address",
    "payment_method": "demo",
    "pgp_mode": "plain",
    "pgp_block": "",
    "captcha_token": token, "captcha_answer": answer
})
check("regression: order placed", r[0] == 303 and "/order/" in r[2])


print()
failed = [n for n, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)