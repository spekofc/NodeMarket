"""Cart management without a single line of JavaScript.

Everything is plain HTML forms posting back; the cart lives in a signed
HttpOnly cookie. Update/remove/clear are separate POST endpoints so the
browser needs no scripting at all.
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import query
from ..security import cart_dump, cart_load, CART_COOKIE
from ..templating import templates

router = APIRouter()


def _hydrate(request: Request):
    cart = cart_load(request.cookies.get("nm_cart", ""))
    ids = list(cart.keys())
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = query(
        f"SELECT * FROM products WHERE id IN ({placeholders}) AND active = 1",
        tuple(ids),
    )
    items = []
    total_cents = 0
    currency = rows[0]["currency"] if rows else "USD"
    for row in rows:
        qty = cart[row["id"]]
        line_total = qty * row["price_cents"]
        total_cents += line_total
        items.append({
            "id": row["id"],
            "name": row["name"],
            "price_cents": row["price_cents"],
            "qty": qty,
            "line_total_cents": line_total,
            "currency": row["currency"],
        })
    return {"items": items, "total_cents": total_cents, "currency": currency}


@router.get("/cart", response_class=HTMLResponse)
def cart_view(request: Request):
    cart = _hydrate(request)
    settings_row = query("SELECT * FROM store_settings WHERE id = 1")
    settings = dict(settings_row[0]) if settings_row else {}
    return templates.TemplateResponse(request, "cart.html", {"cart": cart, "settings": settings})


def _write_cart(response: RedirectResponse, cart: dict[int, int]) -> RedirectResponse:
    if cart:
        response.set_cookie("nm_cart", cart_dump(cart), httponly=True,
                            samesite="lax", path="/", max_age=30 * 24 * 3600)
    else:
        response.delete_cookie("nm_cart", path="/")
    return response


@router.post("/cart/update")
def cart_update(request: Request, pid: int = Form(...), qty: int = Form(1)):
    cart = cart_load(request.cookies.get("nm_cart", ""))
    qty = max(0, min(99, qty))
    if qty == 0:
        cart.pop(pid, None)
    elif qty > 0:
        cart[pid] = qty
    response = RedirectResponse("/cart", status_code=303)
    return _write_cart(response, cart)


@router.post("/cart/remove")
def cart_remove(request: Request, pid: int = Form(...)):
    cart = cart_load(request.cookies.get("nm_cart", ""))
    cart.pop(pid, None)
    response = RedirectResponse("/cart", status_code=303)
    return _write_cart(response, cart)


@router.post("/cart/clear")
def cart_clear(request: Request):
    response = RedirectResponse("/cart", status_code=303)
    return _write_cart(response, {})
