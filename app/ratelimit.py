"""NodeMarket rate limiting: in-memory sliding-window middleware.

- Keyed by (rule, client address) — the address lives only in this process's
  RAM and is never written to disk, files or logs. Old buckets are swept
  automatically on each request pass; nothing persists across restarts.
- Rules protect exactly the sensitive write endpoints:
    admin login POST, checkout POST, captcha SVG GET (image hotlink abuse).
- On limit: 429 with Retry-After. No IP, no log line, nothing stored.
"""

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, Response

# rule -> (max requests, window seconds)
_RULES: dict[str, tuple[int, float]] = {
    "admin_login": (5, 60),
    "checkout": (10, 60),
    "captcha": (200, 60),
    "sell": (10, 60),
    "report": (10, 60),
}

# route signature -> rule name (matched by (method, path))
_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/admin/login"): "admin_login",
    ("POST", "/checkout"): "checkout",
    ("GET", "/captcha.svg"): "captcha",
    ("POST", "/sell"): "sell",
    ("POST", "/product"): "report",  # matched via prefix below
}

_buckets: dict[str, list[float]] = defaultdict(list)
_LAST_SWEEP = 0.0
_SWEEP_EVERY = 30.0  # seconds between background bucket prunes


def _sweep_old_buckets(now: float) -> None:
    """Drop timestamps older than the widest window from every bucket."""
    max_window = max(w for _, w in _RULES.values())
    for key, hits in list(_buckets.items()):
        fresh = [t for t in hits if now - t < max_window]
        if fresh:
            _buckets[key] = fresh
        else:
            _buckets.pop(key, None)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        now = time.time()

        global _LAST_SWEEP
        if now - _LAST_SWEEP > _SWEEP_EVERY:
            _sweep_old_buckets(now)
            _LAST_SWEEP = now

        rule = _ROUTES.get((request.method, request.url.path))
        if rule is None:
            # check prefix routes (e.g., /product/{pid}/report)
            if request.method == "POST" and request.url.path.startswith("/product/") and request.url.path.endswith("/report"):
                rule = "report"
            if rule is None:
                return await call_next(request)

        # Client address in memory only; reset by process restart.
        peer = request.client.host if request.client else "unknown"
        key = f"{rule}|{peer}"
        max_req, window = _RULES[rule]

        hits = _buckets[key]
        fresh = [t for t in hits if now - t < window]
        if len(fresh) >= max_req:
            retry = int(window - (now - fresh[0])) + 1
            return Response(
                "Rate limit exceeded. Try again shortly.",
                status_code=429,
                media_type="text/plain",
                headers={"Retry-After": str(retry)},
            )
        fresh.append(now)
        _buckets[key] = fresh

        return await call_next(request)
