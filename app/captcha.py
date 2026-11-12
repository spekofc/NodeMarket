"""NodeMarket native CAPTCHA: pure-stdlib SVG challenges, zero JavaScript.

- Challenge text (e.g. "7 + 5") is rendered as distorted inline SVG:
  per-glyph rotation/jitter, noise polylines and dots. Nothing is fetched
  from any CDN; the image is served from this same origin.
- The answer is stored ONLY in this process's memory, keyed by a signed,
  expiring token (itsdangerous, 5 minutes, single-use). No database rows,
  no cookies beyond the token hidden field.
- The question is NOT embedded in the token (which is readable base64):
  a bot that reads the token learns nothing. The SVG itself is the only
  place the question appears.
"""

import hashlib
import hmac
import random
import secrets
import time
from html import escape

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

CAPTCHA_MAX_AGE = 300  # 5 minutes
_sw = None  # lazy serializer holder

_challenges: dict[str, tuple[str, str, float]] = {}
_SWEEP_INTERVAL = 64


def _serializer() -> URLSafeTimedSerializer:
    global _sw
    if _sw is None:
        _sw = URLSafeTimedSerializer(settings.secret_key, salt="nodemarket.captcha")
    return _sw


def _answer_digest(answer: str) -> str:
    msg = b"nodemarket-captcha:" + answer.strip().encode("utf-8")
    return hmac.new(settings.secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _make_question() -> tuple[str, str]:
    """Return (question_text, answer_text). Simple arithmetic, unambiguous glyphs."""
    op = random.choice(("+", "-", "+"))
    a = random.randint(2, 9)
    b = random.randint(2, 9)
    if op == "-" and b > a:
        a, b = b, a
    answer = str(a + b) if op == "+" else str(a - b)
    return f"{a} {op} {b}", answer


def new_challenge() -> str:
    """Create a challenge; return the signed token to embed in the form."""
    _sweep()
    question, answer = _make_question()
    token = secrets.token_urlsafe(16)
    _challenges[token] = (question, _answer_digest(answer), time.time())
    return token


def verify(token: str, response: str) -> bool:
    """Single-use check: pops the challenge, validates HMAC of the answer."""
    if not token or not response:
        return False
    entry = _challenges.pop(token, None)
    if entry is None:
        return False
    question, digest, created = entry
    del question
    if time.time() - created > CAPTCHA_MAX_AGE:
        return False
    return hmac.compare_digest(digest, _answer_digest(response))


def _sweep() -> None:
    """Drop expired challenges. Cheap: full scan is bounded by live traffic."""
    now = time.time()
    stale = [t for t, (_, _, created) in _challenges.items() if now - created > CAPTCHA_MAX_AGE]
    for t in stale:
        _challenges.pop(t, None)


# --- SVG rendering -----------------------------------------------------------

_GLYPH_JITTER_X = (-2, 2)
_GLYPH_JITTER_Y = (-4, 4)
_GLYPH_ROT = (-28, 28)
_GLYPH_SIZE = (24, 31)


def _noise_lines(width: int, height: int, count: int) -> list[str]:
    out = []
    for _ in range(count):
        pts = []
        x = random.randint(0, width // 3)
        y = random.randint(0, height)
        for _ in range(3):
            pts.append(f"{x},{y}")
            x = random.randint(0, width)
            y = random.randint(0, height)
        out.append(
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="#888" '
            f'stroke-width="{random.uniform(0.6, 1.4):.2f}" opacity="0.55"/>'
        )
    return out


def _noise_dots(width: int, height: int, count: int) -> list[str]:
    return [
        f'<circle cx="{random.randint(0, width)}" cy="{random.randint(0, height)}" '
        f'r="{random.uniform(0.6, 1.6):.2f}" fill="#666" opacity="0.5"/>'
        for _ in range(count)
    ]


def render_svg(token: str) -> str | None:
    """Render the challenge for this token as a standalone SVG document.

    Returns None when the token is unknown/expired (caller sends 404).
    """
    entry = _challenges.get(token)
    if entry is None:
        return None
    question, _digest, _created = entry
    _sweep()

    width, height = 170, 56
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="captcha challenge">'
        f'<rect width="{width}" height="{height}" fill="#f2f2ef"/>'
    ]

    # glyph soup: each character gets its own transform
    x = 14
    for ch in question:
        if ch == " ":
            x += random.randint(6, 10)
            continue
        size = random.uniform(*_GLYPH_SIZE)
        dx = random.uniform(*_GLYPH_JITTER_X)
        dy = random.uniform(*_GLYPH_JITTER_Y)
        rot = random.uniform(*_GLYPH_ROT)
        y = 38 + dy
        color = random.choice(("#1a1a1a", "#333333", "#0a0a0a"))
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" transform="rotate({rot:.1f} {x:.1f} {y:.1f})" '
            f'font-family="Georgia, serif" font-size="{size:.1f}" font-weight="700" '
            f'fill="{color}">{escape(ch)}</text>'
        )
        x += size * 0.72

    parts.extend(_noise_lines(width, height, 6))
    parts.extend(_noise_dots(width, height, 26))
    parts.append("</svg>")
    return "".join(parts)
