"""Public catalog: storefront and product detail. Zero JS, pure HTML forms."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import query
from ..security import cart_dump, CART_COOKIE
from ..templating import templates

router = APIRouter()


def _product_or_none(pid: int):
    rows = query("SELECT * FROM products WHERE id = ? AND active = 1", (pid,))
    return rows[0] if rows else None


@router.get("/", response_class=HTMLResponse)
def storefront(request: Request):
    products = query("SELECT * FROM products WHERE active = 1 ORDER BY created_at DESC")
    return templates.TemplateResponse(
        request, "index.html", {"products": products}
    )


@router.get("/product/{pid}", response_class=HTMLResponse)
def product_detail(request: Request, pid: int):
    product = _product_or_none(pid)
    if not product:
        return templates.TemplateResponse(request, "not_found.html", {"message": "Product not found."}, status_code=404)
    return templates.TemplateResponse(request, "product.html", {"product": product})


@router.post("/cart/add")
def cart_add(request: Request, pid: int = Form(...), qty: int = Form(1)):
    if not _product_or_none(pid):
        return RedirectResponse("/cart", status_code=303)
    qty = max(1, min(99, qty))
    cart: dict[int, int] = getattr(request.state, "cart", {}) or {}
    cart[pid] = min(99, cart.get(pid, 0) + qty)
    response = RedirectResponse("/cart", status_code=303)
    response.set_cookie(CART_COOKIE, cart_dump(cart), httponly=True,
                        samesite="lax", path="/", max_age=30 * 24 * 3600)
    return response
