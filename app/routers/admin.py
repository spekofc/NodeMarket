"""Admin panel: password-gated product/order/settings management.

Buyer data is only ever shown as PGP ciphertext - the owner decrypts it
locally with their private key. The server cannot read it.
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import captcha
from ..db import query, execute
from ..pgp import validate_public_key
from ..payments import get_provider
from ..payments import escrow
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
    token = captcha.new_challenge()
    return templates.TemplateResponse(request, "admin/login.html", {"captcha_token": token})


@router.post("/login")
def login_submit(request: Request, password: str = Form(""),
                 captcha_token: str = Form(""), captcha_answer: str = Form("")):
    # CAPTCHA first: brute force never even reaches the password check.
    if not captcha.verify(captcha_token, captcha_answer):
        token = captcha.new_challenge()
        return templates.TemplateResponse(
            request, "admin/login.html",
            {"error": "Wrong or expired captcha answer.", "captcha_token": token},
            status_code=401,
        )
    if not verify_admin_password(password):
        token = captcha.new_challenge()
        return templates.TemplateResponse(
            request, "admin/login.html",
            {"error": "Wrong password.", "captcha_token": token},
            status_code=401,
        )
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
    order = escrow.get_order(order_ref)
    if not order:
        return templates.TemplateResponse(request, "not_found.html", {"message": "Order not found."}, status_code=404)
    items = query("SELECT * FROM order_items WHERE order_id = ?", (order["id"],))
    events = escrow.get_events(order["id"]) if order["settlement_mode"] == "escrow" else []
    messages = query("SELECT * FROM order_messages WHERE order_id = ? ORDER BY id", (order["id"],))
    return templates.TemplateResponse(
        request, "admin/order.html",
        {"order": order, "items": items, "events": events, "messages": messages,
         "allowed_status": sorted(escrow.TRANSITIONS[order["settlement_mode"]]
                                  .get(order["status"], []))})


@router.post("/orders/{order_ref}/status")
def order_set_status(request: Request, order_ref: str, status: str = Form(...)):
    guard = _guard(request)
    if guard:
        return guard
    order = escrow.get_order(order_ref)
    if not order:
        return RedirectResponse("/admin", status_code=303)
    # Validated against the state machine - no silent lifecycle corruption.
    try:
        escrow.transition(order, status, "admin")
    except escrow.TransitionError:
        pass  # illegal move: just reload the page
    return RedirectResponse(f"/admin/orders/{order_ref}", status_code=303)


# --- products -------------------------------------------------------------------

def _slugify(name: str) -> str:
    """URL-safe slug: lowercase, alnum runs joined by single dashes."""
    import re as _re
    slug = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "category"


@router.get("/categories", response_class=HTMLResponse)
def categories_view(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    categories = query(
        """SELECT c.*, (SELECT COUNT(*) FROM products p
                        WHERE p.category_id = c.id) AS product_count
           FROM categories c ORDER BY name COLLATE NOCASE""")
    return templates.TemplateResponse(request, "admin/categories.html",
                                      {"categories": categories})


@router.post("/categories/new")
def category_create(request: Request, name: str = Form("")):
    guard = _guard(request)
    if guard:
        return guard
    name = name.strip()[:60]
    if name:
        slug = _slugify(name)
        existing = query("SELECT slug FROM categories WHERE slug = ?", (slug,))
        if existing:
            n = 2
            while query("SELECT slug FROM categories WHERE slug = ?", (f"{slug}-{n}",)):
                n += 1
            slug = f"{slug}-{n}"
        execute("INSERT INTO categories (name, slug) VALUES (?, ?)", (name, slug))
    return RedirectResponse("/admin/categories", status_code=303)


@router.get("/categories/{cid}/edit", response_class=HTMLResponse)
def category_edit(request: Request, cid: int):
    guard = _guard(request)
    if guard:
        return guard
    rows = query("SELECT * FROM categories WHERE id = ?", (cid,))
    if not rows:
        return RedirectResponse("/admin/categories", status_code=303)
    return templates.TemplateResponse(request, "admin/category_form.html",
                                      {"category": rows[0]})


@router.post("/categories/{cid}/edit")
def category_update(request: Request, cid: int, name: str = Form("")):
    guard = _guard(request)
    if guard:
        return guard
    name = name.strip()[:60]
    if name:
        slug = _slugify(name)
        clash = query("SELECT id FROM categories WHERE slug = ? AND id != ?", (slug, cid))
        if clash:
            n = 2
            while query("SELECT slug FROM categories WHERE slug = ? AND id != ?",
                        (f"{slug}-{n}", cid)):
                n += 1
            slug = f"{slug}-{n}"
        execute("UPDATE categories SET name = ?, slug = ? WHERE id = ?", (name, slug, cid))
    return RedirectResponse("/admin/categories", status_code=303)


@router.post("/categories/{cid}/delete")
def category_delete(request: Request, cid: int):
    guard = _guard(request)
    if guard:
        return guard
    execute("UPDATE products SET category_id = NULL WHERE category_id = ?", (cid,))
    execute("DELETE FROM categories WHERE id = ?", (cid,))
    return RedirectResponse("/admin/categories", status_code=303)


@router.get("/products", response_class=HTMLResponse)
def products_view(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    products = query(
        """SELECT p.*, c.name AS category_name
           FROM products p LEFT JOIN categories c ON c.id = p.category_id
           ORDER BY p.id DESC""")
    return templates.TemplateResponse(request, "admin/products.html", {"products": products})


def _product_categories():
    return query("SELECT * FROM categories ORDER BY name COLLATE NOCASE")


@router.get("/products/new", response_class=HTMLResponse)
def product_new(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    return templates.TemplateResponse(request, "admin/product_form.html",
                                      {"product": None, "categories": _product_categories()})


def _clean_category(value: str) -> int | None:
    try:
        cid = int(value)
    except (TypeError, ValueError):
        return None
    return cid if query("SELECT id FROM categories WHERE id = ?", (cid,)) else None


@router.post("/products/new")
def product_create(request: Request, name: str = Form(""), description: str = Form(""),
                   price: str = Form("0"), category_id: str = Form("")):
    guard = _guard(request)
    if guard:
        return guard
    try:
        price_cents = round(float(price.replace(",", ".")) * 100)
    except ValueError:
        price_cents = 0
    if name.strip():
        execute(
            "INSERT INTO products (name, description, price_cents, category_id) VALUES (?, ?, ?, ?)",
            (name.strip(), description.strip(), max(0, price_cents), _clean_category(category_id)),
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
    return templates.TemplateResponse(request, "admin/product_form.html",
                                      {"product": product, "categories": _product_categories()})


@router.post("/products/{pid}/edit")
def product_update(request: Request, pid: int, name: str = Form(""),
                   description: str = Form(""), price: str = Form("0"),
                   active: str = Form(""), category_id: str = Form("")):
    guard = _guard(request)
    if guard:
        return guard
    try:
        price_cents = round(float(price.replace(",", ".")) * 100)
    except ValueError:
        price_cents = 0
    execute(
        """UPDATE products SET name = ?, description = ?, price_cents = ?,
           active = ?, category_id = ? WHERE id = ?""",
        (name.strip(), description.strip(), max(0, price_cents),
         1 if active else 0, _clean_category(category_id), pid),
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
        "provider_valid": get_provider(row["payment_provider"]) is not None,
    })


def _flag(form_value: str) -> int:
    return 1 if form_value else 0


@router.post("/settings")
def settings_update(request: Request, store_name: str = Form(""),
                    pgp_public_key: str = Form(""),
                    btc_enabled: str = Form(""), btc_mode: str = Form("xpub"),
                    btc_rate: str = Form(""), xpub: str = Form(""),
                    xmr_enabled: str = Form(""), xmr_address: str = Form(""),
                    xmr_subaddresses: str = Form(""), xmr_rate: str = Form(""),
                    demo_enabled: str = Form(""),
                    payout_btc_address: str = Form(""),
                    payout_xmr_address: str = Form(""),
                    settlement_mode: str = Form("direct")):
    guard = _guard(request)
    if guard:
        return guard
    settlement = settlement_mode if settlement_mode in {"direct", "escrow"} else "direct"
    btc_mode = btc_mode if btc_mode in {"xpub", "rpc"} else "xpub"
    execute(
        """UPDATE store_settings
           SET store_name = ?, pgp_public_key = ?,
               btc_enabled = ?, btc_mode = ?, btc_rate = ?, xpub = ?,
               xmr_enabled = ?, xmr_address = ?, xmr_subaddresses = ?,
               xmr_rate = ?, demo_enabled = ?,
               payout_btc_address = ?, payout_xmr_address = ?,
               settlement_mode = ?
           WHERE id = 1""",
        (store_name.strip() or "NodeMarket Store", pgp_public_key.strip(),
         _flag(btc_enabled), btc_mode, btc_rate.strip(), xpub.strip(),
         _flag(xmr_enabled), xmr_address.strip(), xmr_subaddresses.strip(),
         xmr_rate.strip(), _flag(demo_enabled),
         payout_btc_address.strip(), payout_xmr_address.strip(),
         settlement),
    )
    return RedirectResponse("/admin/settings", status_code=303)


# --- reports moderation ----------------------------------------------------------

@router.get("/reports", response_class=HTMLResponse)
def reports_view(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    reports = query(
        """SELECT r.*, p.name AS product_name
           FROM reports r
           JOIN products p ON p.id = r.product_id
           ORDER BY r.id DESC""")
    return templates.TemplateResponse(request, "admin/reports.html", {"reports": reports})


@router.post("/reports/{rid}/archive")
def report_archive(request: Request, rid: int):
    guard = _guard(request)
    if guard:
        return guard
    execute("UPDATE reports SET status = 'archived' WHERE id = ?", (rid,))
    return RedirectResponse("/admin/reports", status_code=303)


@router.post("/reports/{rid}/action")
def report_action(request: Request, rid: int):
    """Mark report as actioned and deactivate the product."""
    guard = _guard(request)
    if guard:
        return guard
    row = query("SELECT product_id FROM reports WHERE id = ?", (rid,))
    if row:
        execute("UPDATE products SET active = 0 WHERE id = ?", (row[0]["product_id"],))
        execute("UPDATE reports SET status = 'actioned' WHERE id = ?", (rid,))
    return RedirectResponse("/admin/reports", status_code=303)
