"""Admin panel: password-gated product/order/settings management.

Buyer data is only ever shown as PGP ciphertext - the owner decrypts it
locally with their private key. The server cannot read it.
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import query, execute
from ..pgp import validate_public_key
from ..payments import get_provider, available
from ..security import (ADMIN_COOKIE, ADMIN_MAX_AGE, admin_session_create,
                        admin_session_valid, verify_admin_password)
from ..templating import templates

router = APIRouter(prefix="/admin")


def _authed(request: Request) -> bool:
    return admin_session_valid(request.cookies.get(ADMIN_COOKIE))


def _guard(request: Request):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    return None


# --- auth ---------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
def login_view(request: Request):
    if _authed(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {})


@router.post("/login")
def login_submit(request: Request, password: str = Form("")):
    if not verify_admin_password(password):
        return templates.TemplateResponse(request, "admin/login.html",
                                          {"error": "Wrong password."}, status_code=401)
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(ADMIN_COOKIE, admin_session_create(), httponly=True,
                        samesite="lax", path="/", max_age=ADMIN_MAX_AGE)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return response


# --- dashboard / orders ---------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    orders = query(
        """SELECT id, order_ref, status, total_cents, currency,
                  payment_provider, created_at
           FROM orders ORDER BY id DESC LIMIT 200"""
    )
    return templates.TemplateResponse(request, "admin/dashboard.html", {"orders": orders})


@router.get("/orders/{order_ref}", response_class=HTMLResponse)
def order_detail(request: Request, order_ref: str):
    guard = _guard(request)
    if guard:
        return guard
    rows = query("SELECT * FROM orders WHERE order_ref = ?", (order_ref,))
    if not rows:
        return templates.TemplateResponse(request, "not_found.html", {"message": "Order not found."}, status_code=404)
    order = dict(rows[0])
    items = query("SELECT * FROM order_items WHERE order_id = ?", (order["id"],))
    return templates.TemplateResponse(request, "admin/order.html", {"order": order, "items": items})


@router.post("/orders/{order_ref}/status")
def order_set_status(request: Request, order_ref: str, status: str = Form(...)):
    guard = _guard(request)
    if guard:
        return guard
    if status not in {"pending", "paid", "completed", "cancelled"}:
        return RedirectResponse(f"/admin/orders/{order_ref}", status_code=303)
    execute("UPDATE orders SET status = ? WHERE order_ref = ?", (status, order_ref))
    return RedirectResponse(f"/admin/orders/{order_ref}", status_code=303)


# --- products -------------------------------------------------------------------

@router.get("/products", response_class=HTMLResponse)
def products_view(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    products = query("SELECT * FROM products ORDER BY id DESC")
    return templates.TemplateResponse(request, "admin/products.html", {"products": products})


@router.get("/products/new", response_class=HTMLResponse)
def product_new(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    return templates.TemplateResponse(request, "admin/product_form.html", {"product": None})


@router.post("/products/new")
def product_create(request: Request, name: str = Form(""), description: str = Form(""),
                   price: str = Form("0")):
    guard = _guard(request)
    if guard:
        return guard
    try:
        price_cents = round(float(price.replace(",", ".")) * 100)
    except ValueError:
        price_cents = 0
    if name.strip():
        execute(
            "INSERT INTO products (name, description, price_cents) VALUES (?, ?, ?)",
            (name.strip(), description.strip(), max(0, price_cents)),
        )
    return RedirectResponse("/admin/products", status_code=303)


@router.get("/products/{pid}/edit", response_class=HTMLResponse)
def product_edit(request: Request, pid: int):
    guard = _guard(request)
    if guard:
        return guard
    rows = query("SELECT * FROM products WHERE id = ?", (pid,))
    if not rows:
        return RedirectResponse("/admin/products", status_code=303)
    product = dict(rows[0])
    product["price_display"] = f"{product['price_cents'] / 100:.2f}"
    return templates.TemplateResponse(request, "admin/product_form.html", {"product": product})


@router.post("/products/{pid}/edit")
def product_update(request: Request, pid: int, name: str = Form(""),
                   description: str = Form(""), price: str = Form("0"),
                   active: str = Form("")):
    guard = _guard(request)
    if guard:
        return guard
    try:
        price_cents = round(float(price.replace(",", ".")) * 100)
    except ValueError:
        price_cents = 0
    execute(
        """UPDATE products SET name = ?, description = ?, price_cents = ?, active = ?
           WHERE id = ?""",
        (name.strip(), description.strip(), max(0, price_cents), 1 if active else 0, pid),
    )
    return RedirectResponse("/admin/products", status_code=303)


@router.post("/products/{pid}/delete")
def product_delete(request: Request, pid: int):
    guard = _guard(request)
    if guard:
        return guard
    execute("DELETE FROM products WHERE id = ?", (pid,))
    return RedirectResponse("/admin/products", status_code=303)


# --- settings -------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
def settings_view(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    row = dict(query("SELECT * FROM store_settings WHERE id = 1")[0])
    key_ok, key_msg = validate_public_key(row["pgp_public_key"] or "")
    return templates.TemplateResponse(request, "admin/settings.html", {
        "settings": row,
        "key_ok": key_ok,
        "key_msg": key_msg,
        "providers": available(),
        "provider_valid": get_provider(row["payment_provider"]) is not None,
    })


@router.post("/settings")
def settings_update(request: Request, store_name: str = Form(""),
                    pgp_public_key: str = Form(""),
                    payment_provider: str = Form("demo"), xpub: str = Form("")):
    guard = _guard(request)
    if guard:
        return guard
    provider = payment_provider if get_provider(payment_provider) else "demo"
    execute(
        """UPDATE store_settings
           SET store_name = ?, pgp_public_key = ?, payment_provider = ?, xpub = ?
           WHERE id = 1""",
        (store_name.strip() or "NodeMarket Store", pgp_public_key.strip(),
         provider, xpub.strip()),
    )
    return RedirectResponse("/admin/settings", status_code=303)
