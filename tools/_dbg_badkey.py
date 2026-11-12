import urllib.request, urllib.parse, re, sqlite3, http.cookiejar, sys
sys.path.insert(0, '.')
from app import pgp_compat
from pgpy import PGPKey, PGPUID, PGPMessage
from pgpy.constants import PubKeyAlgorithm, KeyFlags, HashAlgorithm, SymmetricKeyAlgorithm, CompressionAlgorithm

BASE = 'http://127.0.0.1:8000'

buyer = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def get(path):
    return buyer.open(BASE+path).read().decode()

def post(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE+path, data=body, method='POST')
    try: return buyer.open(req).status, buyer.open(req).read().decode(), buyer.open(req).geturl()
    except urllib.error.HTTPError as e: return e.code, e.read().decode(), e.geturl()

def solve(html):
    m = re.search(r'/captcha\.svg\?token=([A-Za-z0-9_-]+)', html)
    t = m.group(1)
    svg = urllib.request.urlopen('http://127.0.0.1:8000/captcha.svg?token=' + t).read().decode()
    glyphs = re.findall(r'<text [^>]*>([^<]+)</text>', svg)
    q = ''.join(glyphs)
    m2 = re.match(r'^(\d+)\s*([+\-])\s*(\d+)$', q)
    return t, str(int(m2.group(1))+int(m2.group(3)) if m2.group(2)=='+' else int(m2.group(1))-int(m2.group(3)))

# Set store key to garbage
conn = sqlite3.connect('data/nodemarket.db')
conn.execute("UPDATE store_settings SET pgp_public_key = '-----BEGIN GARBAGE-----'")
conn.commit()
conn.close()

# Create buyer key and BYO block
buyer_key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
buyer_key.add_uid(PGPUID.new('Buyer <buyer@test.local>'),
    usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
    hashes=[HashAlgorithm.SHA256], ciphers=[SymmetricKeyAlgorithm.AES256],
    compression=[CompressionAlgorithm.ZLIB])
MARKER = 'Shopper Street 77, Basement Flat, Torville'
buyer_msg = PGPMessage.new(MARKER)
BYO_BLOCK = str(buyer_key.pubkey.encrypt(buyer_msg))

# Find active product
conn = sqlite3.connect('data/nodemarket.db')
prod = conn.execute('SELECT id FROM products WHERE active = 1 LIMIT 1').fetchone()
pid = prod[0] if prod else '1'
conn.close()

buyer = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

# Add to cart
post('/cart/add', {'pid': str(pid), 'qty': '1'})
html = get('/checkout')
print('Checkout page key_ok false:', 'Store PGP key is missing or invalid' in html)
print('Checkout page has BYO option:', 'Bring your own PGP' in html)

# Try BYO order
t, a = solve(html)
print('captcha_token:', t, 'answer:', a)
status, html, url = post('/checkout', {
    'payment_method': 'demo',
    'pgp_mode': 'own',
    'pgp_block': BYO_BLOCK,
    'delivery_details': '',
    'captcha_token': t, 'captcha_answer': a
})
print('BYO order status:', status, 'url:', url)
print('Error in html:', 'PGP' in html or 'error' in html.lower())
if status != 200:
    print('Error snippet:', html[:2000])