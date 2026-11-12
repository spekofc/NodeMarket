"""NodeMarket application entrypoint.

Hard security headers, zero-JS frontend, zero request logging, no IP storage.
"""

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from urllib.parse import urlparse

from .config import settings
from .db import init_db
from .templating import templates
from .routers import catalog, cart, checkout, admin

CSP = (
    "default-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "script-src 'none'; "            # hard zero-JS declaration
    "form-action 'self'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return response


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin form posts (CSRF hardening without tokens/JS)."""

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request: Request, call_next):
        if request.method not in self.SAFE_METHODS:
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            if origin:
                origin_host = urlparse(origin).netloc
                if origin_host and origin_host != host:
                    return HTMLResponse("Cross-origin request rejected.", status_code=403)
        return await call_next(request)


class CartLoadMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from .security import cart_load
        request.state.cart = cart_load(request.cookies.get("nm_cart", ""))
        return await call_next(request)


def create_app() -> FastAPI:
    app = FastAPI(title="NodeMarket", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CartLoadMiddleware)
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    app.mount("/static", StaticFiles(directory="static"), name="static")

    app.include_router(catalog.router)
    app.include_router(cart.router)
    app.include_router(checkout.router)
    app.include_router(admin.router)

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


app = create_app()
