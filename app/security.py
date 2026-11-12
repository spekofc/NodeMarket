"""NodeMarket security helpers.

- Signed, HttpOnly, SameSite=Lax cookies via itsdangerous (cart + admin session).
- Constant-time admin password check.
- Origin check middleware lives in app.main; this module holds the serializers.
"""

import hmac
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer, SignatureExpired

from .config import settings

_cart_serializer = URLSafeTimedSerializer(settings.secret_key, salt="nodemarket.cart")
_admin_serializer = URLSafeTimedSerializer(settings.secret_key, salt="nodemarket.admin")

CART_COOKIE = "nm_cart"
ADMIN_COOKIE = "nm_admin"
CART_MAX_AGE = 30 * 24 * 3600   # 30 days
ADMIN_MAX_AGE = 12 * 3600       # 12 hours


def cart_dump(data: dict[int, int]) -> str:
    return _cart_serializer.dumps(data)


def cart_load(value: str) -> dict[int, int]:
    try:
        raw = _cart_serializer.loads(value, max_age=CART_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return {}
    if not isinstance(raw, dict):
        return {}
    clean: dict[int, int] = {}
    for k, v in raw.items():
        try:
            pid, qty = int(k), int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= qty <= 99 and pid > 0:
            clean[pid] = qty
    return clean


def admin_session_create() -> str:
    return _admin_serializer.dumps({"session": True})


def admin_session_valid(value: str | None) -> bool:
    if not value:
        return False
    try:
        _admin_serializer.loads(value, max_age=ADMIN_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def verify_admin_password(candidate: str) -> bool:
    return hmac.compare_digest(
        candidate.encode("utf-8"), settings.admin_password.encode("utf-8")
    )
