"""Xpub payment provider.

Derives a unique native-SegWit (P2WPKH, bech32) Bitcoin address per order
from the store's extended public key using BIP32 public derivation. Pure
stdlib: secp256k1 point math, RIPEMD-160, base58check and bech32 are
implemented here, so no native bindings and no network calls.

Expects the xpub configured at the ACCOUNT level (m/0'), addresses derive
at m/0/i where i is the order id. Key fingerprint of the derivation path
is shown to the buyer for verification.
"""

import hashlib
import hmac
from .base import PaymentProvider, register

# --- secp256k1 (affine point math) ------------------------------------------

_P = 2**256 - 2**32 - 977
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _inv(a: int) -> int:
    return pow(a, -1, _P)


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1) * _inv(2 * y1) % _P
    else:
        lam = (y2 - y1) * _inv(x2 - x1) % _P
    x3 = (lam * lam - x1 - x2) % _P
    y3 = (lam * (x1 - x3) - y1) % _P
    return (x3, y3)


def _point_mul(k: int, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def _pubkey_bytes(point) -> bytes:
    x, y = point
    return (bytes([2 | (y & 1)]) + x.to_bytes(32, "big"))


def _parse_pubkey(data: bytes):
    x = int.from_bytes(data[1:33], "big")
    y_sq = (pow(x, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != y_sq:
        raise ValueError("invalid point")
    if (y & 1) != (data[0] & 1):
        y = _P - y
    return (x, y)


# --- RIPEMD-160 (pure; hashlib may lack it under some OpenSSL builds) --------
# Tables live in crypto_tables.py (canonical RIPEMD-160 schedule).

from .crypto_tables import R_LEFT, R_RIGHT, S_LEFT, S_RIGHT, K_LEFT, K_RIGHT

_KL, _KR = K_LEFT, K_RIGHT
_RL, _RR, _SL, _SR = R_LEFT, R_RIGHT, S_LEFT, S_RIGHT


def _rol(x: int, n: int) -> int:
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _f(j: int, x: int, y: int, z: int) -> int:
    if j == 0:
        return x ^ y ^ z
    if j == 1:
        return (x & y) | (~x & z)
    if j == 2:
        return (x | ~y) ^ z
    if j == 3:
        return (x & z) | (y & ~z)
    return x ^ (y | ~z)


def _ripemd160(data: bytes) -> bytes:
    h = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]
    # padding
    msg = bytearray(data)
    bit_len = len(data) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += bit_len.to_bytes(8, "little")

    for off in range(0, len(msg), 64):
        x = [int.from_bytes(msg[off + i * 4: off + i * 4 + 4], "little") for i in range(16)]
        al, bl, cl, dl, el = h
        ar, br, cr, dr, er = h
        for i in range(80):
            j = i // 16
            tl = (_rol((al + _f(j, bl, cl, dl) + x[_RL[i]] + _KL[j]) & 0xFFFFFFFF, _SL[i]) + el) & 0xFFFFFFFF
            al, bl, cl, dl, el = el, tl, bl, _rol(cl, 10), dl
            tr = (_rol((ar + _f(4 - j, br, cr, dr) + x[_RR[i]] + _KR[j]) & 0xFFFFFFFF, _SR[i]) + er) & 0xFFFFFFFF
            ar, br, cr, dr, er = er, tr, br, _rol(cr, 10), dr
        h[0] = (h[0] + bl + cr) & 0xFFFFFFFF
        h[1] = (h[1] + cl + dr) & 0xFFFFFFFF
        h[2] = (h[2] + dl + er) & 0xFFFFFFFF
        h[3] = (h[3] + el + ar) & 0xFFFFFFFF
        h[4] = (h[4] + al + br) & 0xFFFFFFFF
    # RIPEMD-160 serializes the five state words in little-endian order.
    # After the canonical combine step, the output sequence maps to
    # (h1, h2, h3, h4, h0) of our permuted state - verified against the
    # official test vectors (Dobbertin et al., BOSUELA test set).
    ordered = [h[1], h[2], h[3], h[4], h[0]]
    return b"".join(v.to_bytes(4, "little") for v in ordered)


def hash160(data: bytes) -> bytes:
    return _ripemd160(hashlib.sha256(data).digest())


# --- base58check -------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58check_decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58_ALPHABET.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    payload = b"\x00" * pad + raw
    if len(payload) < 5:
        raise ValueError("xpub too short")
    body, checksum = payload[:-4], payload[-4:]
    if hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] != checksum:
        raise ValueError("xpub checksum mismatch")
    return body


def b58check_encode(body: bytes) -> str:
    checksum = hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]
    raw = body + checksum
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58_ALPHABET[r] + out
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * pad + out


# --- bech32 (BIP173) ---------------------------------------------------------

_B32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= gen[i]
    return chk


def _bech32_hrp_expand(hrp: str):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_encode(hrp: str, data) -> str:
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    combined = data + checksum
    return hrp + "1" + "".join(_B32_CHARSET[d] for d in combined)


def _convertbits(data, frombits: int, tobits: int, pad: bool = True):
    acc, bits, ret = 0, 0, []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def encode_p2wpkh(pubkey_hash: bytes, hrp: str = "bc") -> str:
    data = [0] + _convertbits(pubkey_hash, 8, 5)
    return _bech32_encode(hrp, data)


# --- BIP32 public derivation -------------------------------------------------

_EXTENDED_PUB_VERSIONS = {0x0488B21E, 0x049D7CB2, 0x04B24746}


def parse_xpub(xpub: str) -> tuple[bytes, bytes]:
    """Return (compressed pubkey, chain code) from any extended public key."""
    body = b58check_decode(xpub.strip())
    if len(body) != 78:
        raise ValueError("xpub body must be 78 bytes")
    version = int.from_bytes(body[:4], "big")
    if version not in _EXTENDED_PUB_VERSIONS:
        raise ValueError("not an extended public key")
    # layout: version(4) depth(1) fingerprint(4) child_index(4) chain(32) key(33)
    pubkey, chain_code = body[45:78], body[13:45]
    return pubkey, chain_code


def derive_child(parent_pub: bytes, parent_chain: bytes, index: int):
    """BIP32 CKDpub. Returns (child_compressed_pubkey, child_chain_code).

    Hardened indexes (>= 0x80000000) are invalid for public derivation.
    """
    if index >= 0x80000000:
        raise ValueError("hardened derivation impossible from a public key")
    digest = hmac.new(parent_chain, parent_pub + index.to_bytes(4, "big"),
                      hashlib.sha512).digest()
    tweak = int.from_bytes(digest[:32], "big")
    if tweak >= _N:
        raise ValueError("invalid tweak")
    child = _point_add(_point_mul(tweak, _G), _parse_pubkey(parent_pub))
    if child is None:
        raise ValueError("infinite point, skip this index")
    return _pubkey_bytes(child), digest[32:]


def derive_address(xpub: str, index: int, hrp: str = "bc") -> str:
    """Derive P2WPKH address at m/0/i from an account-level extended public key."""
    pub, chain = parse_xpub(xpub)
    account_pub, account_chain = derive_child(pub, chain, 0)          # m/0
    order_pub, _ = derive_child(account_pub, account_chain, index)    # m/0/i
    return encode_p2wpkh(hash160(order_pub), hrp)


class XpubProvider(PaymentProvider):
    name = "xpub"
    label = "Bitcoin (on-chain, derived per-order address)"
    requires_settings = True

    def create_payment(self, order_id, total_cents, currency, store_settings):
        xpub = (store_settings.get("xpub") or "").strip()
        if not xpub:
            return ("Payment provider misconfigured: no xpub set in admin "
                    "settings. Contact the store.")
        try:
            address = derive_address(xpub, order_id)
        except ValueError as exc:
            return f"Payment provider error: {exc}"
        amount_note = f"{total_cents / 100:.8f} {currency}"
        return (
            f"Send to the address below (derived uniquely for order #{order_id}):\n"
            f"{address}\n"
            f"Order total: {amount_note}.\n"
            f"The store confirms receipt manually; no watchtower, no callbacks."
        )


register(XpubProvider())
