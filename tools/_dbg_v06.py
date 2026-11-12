"""Debug v06 test."""
import sys, urllib.parse, urllib.request, urllib.error, http.cookiejar, re, sqlite3
sys.path.insert(0, ".")
from app import pgp_compat

BASE = "http://127.0.0.1:8000"

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
buyer = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def get(path):
    return opener.open(BASE+path).read().decode()
def bget(path):
    return buyer.open(BASE+path).read().decode()
def bpost(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE+path, data=body, method="POST")
    try: return buyer.open(req).status, buyer.open(req).read().decode(), buyer.open(req).geturl()
    except urllib.error.HTTPError as e: return e.code, e.read().decode(), e.geturl()
def apost(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE+path, data=body, method="POST")
    try: return opener.open(req).status, opener.open(req).read().decode(), opener.open(req).geturl()
    except urllib.error.HTTPError as e: return e.code, e.read().decode(), e.geturl()

def solve(html):
    m = re.search(r'/captcha\.svg\?token=([A-Za-z0-9_-]+)', html)
    t = m.group(1)
    print(f"captcha token: {t}")
    svg = get(f"/captcha.svg?token={t}")
    print(f"svg length: {len(svg)}")
    glyphs = re.findall(r"<text [^>]*>([^<]+)</text>", svg)
    print(f"glyphs: {glyphs}")
    q = "".join(glyphs)
    m2 = re.match(r"^(\d+)\s*([+\-])\s*(\d+)$", q)
    print(f"question: {q}, parsed: {m2}")
    return t, str(int(m2.group(1))+int(m2.group(3)) if m2.group(2)=="+" else int(m2.group(1))-int(m2.group(3)))

# admin login
s = get("/admin/login")
t, a = solve(s)
opener.open(urllib.request.Request(BASE+"/admin/login", data=urllib.parse.urlencode({
    "captcha_token": t, "captcha_answer": a, "password": "changeme-admin"}).encode(), method="POST"))

# seed category
conn = sqlite3.connect("data/nodemarket.db")
conn.execute("INSERT INTO categories (name, slug) VALUES ('Electronics', 'electronics')")
conn.commit()
conn.close()

# admin settings
from pgpy import PGPKey, PGPUID
from pgpy.constants import PubKeyAlgorithm, KeyFlags, HashAlgorithm, SymmetricKeyAlgorithm, CompressionAlgorithm
store_key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
store_key.add_uid(PGPUID.new("Store <store@test.local>"),
    usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
    hashes=[HashAlgorithm.SHA256], ciphers=[SymmetricKeyAlgorithm.AES256],
    compression=[CompressionAlgorithm.ZLIB])
STORE_PUB = str(store_key.pubkey)
apost("/admin/settings", {
    "store_name": "NodeMarket Store", "settlement_mode": "direct",
    "demo_enabled": "on", "pgp_public_key": STORE_PUB, "listing_policy": "moderated"})

# GET /sell
html = bget("/sell")
print("sell page:", "Sell" in html)

# submit listing
html = bget("/sell")
t, a = solve(html)
status, html, url = bpost("/sell", {
    "name": "Raspberry Pi 5 8GB", "description": "Brand new, sealed box",
    "price": "120.00", "currency": "USD", "category_id": "1",
    "payout_address": "bc1qtest...", "captcha_token": t, "captcha_answer": a
})
print("submit status:", status)
print("success page snippet:", html[:2000])

# extract seller_token
m = re.search(r"(?:seller[_-]?token|token)[^a-f0-9]*([a-f0-9]{32})", html, re.I)
print("token regex match:", m)
if m: print("token:", m.group(1))

# try other patterns
m2 = re.search(r"seller_token[^a-f0-9]*([a-f0-9]{32})", html, re.I)
print("token2:", m2.group(1) if m2 else None)

m3 = re.search(r"([a-f0-9]{32})", html)
print("first 32-char hex:", m3.group(1) if m3 else None)

# check DB
conn = sqlite3.connect("data/nodemarket.db")
rows = conn.execute("SELECT id, seller_token, status FROM seller_listings").fetchall()
print("DB listings:", rows)
conn.close()