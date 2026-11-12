"""Public catalog: storefront and product detail. Zero JS, pure HTML forms."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import captcha
from ..db import query, execute
from ..security import cart_dump, CART_COOKIE
from ..templating import templates

router = APIRouter()


def _product_or_none(pid: int):
    rows = query("SELECT * FROM products WHERE id = ? AND active = 1", (pid,))
    return rows[0] if rows else None


def _search_products(term: str, category_id: int | None):
    """SQLite LIKE search over title/description, optional category filter.
    Includes both admin products and approved seller listings.
    """
    # Admin products
    sql = """SELECT id, name, description, price_cents, currency, category_id, created_at
             FROM products WHERE active = 1"""
    params: list = []
    if category_id is not None:
        sql += " AND category_id = ?"
        params.append(category_id)
    if term:
        sql += " AND (name LIKE ? OR description LIKE ?)"
        like = f"%{term}%"
        params += [like, like]

    # Approved seller listings - match same columns
    seller_sql = """SELECT id, name, description, price_cents, currency, category_id, created_at
                    FROM seller_listings WHERE status = 'active'"""
    if category_id is not None:
        seller_sql += " AND category_id = ?"
        params.append(category_id)
    if term:
        seller_sql += " AND (name LIKE ? OR description LIKE ?)"
        like = f"%{term}%"
        params += [like, like]

    sql = f"{sql} UNION ALL {seller_sql} ORDER BY created_at DESC"
    return query(sql, tuple(params))


@router.get("/", response_class=HTMLResponse)
def storefront(request: Request, q: str = "", category: str = ""):
    categories = query("SELECT * FROM categories ORDER BY name COLLATE NOCASE")
    active = None
    slug_match = False
    if category:
        match = [c for c in categories if c["slug"] == category]
        if match:
            active = match[0]["id"]
            slug_match = True
        else:
            # unknown slug -> no products match
            active = -1
    term = (q or "").strip()
    products = _search_products(term, active)
    return templates.TemplateResponse(request, "index.html", {
        "products": products,
        "categories": categories,
        "active_category": category,
        "active_category_valid": slug_match,
        "search_term": term,
    })


def _product_or_none(pid: int, include_seller: bool = False):
    rows = query("SELECT * FROM products WHERE id = ? AND active = 1", (pid,))
    if rows:
        return rows[0]
    if include_seller:
        rows = query("SELECT * FROM seller_listings WHERE id = ? AND status = 'active'", (pid,))
        if rows:
            return rows[0]
    return None


@router.get("/product/{pid}", response_class=HTMLResponse)
def product_detail(request: Request, pid: int):
    product = _product_or_none(pid, include_seller=True)
    if not product:
        return templates.TemplateResponse(request, "not_found.html", {"message": "Product not found."}, status_code=404)
    category = None
    if product["category_id"]:
        rows = query("SELECT * FROM categories WHERE id = ?", (product["category_id"],))
        category = rows[0] if rows else None
    return templates.TemplateResponse(request, "product.html", {
        "product": product, "category": category})


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


# --- product reporting (zero-JS, CAPTCHA-protected) --------------------------

@router.get("/product/{pid}/report", response_class=HTMLResponse)
def report_view(request: Request, pid: int):
    product = _product_or_none(pid)
    if not product:
        return templates.TemplateResponse(request, "not_found.html", {"message": "Product not found."}, status_code=404)
    return templates.TemplateResponse(request, "report.html", {
        "product": product, "captcha_token": captcha.new_challenge()})


@router.post("/product/{pid}/report")
def report_submit(request: Request, pid: int,
                  reason: str = Form(""), description: str = Form(""),
                  captcha_token: str = Form(""), captcha_answer: str = Form("")):
    product = _product_or_none(pid)
    if not product:
        return templates.TemplateResponse(request, "not_found.html", {"message": "Product not found."}, status_code=404)

    if not captcha.verify(captcha_token, captcha_answer):
        return templates.TemplateResponse(request, "report.html", {
            "product": product,
            "captcha_token": captcha.new_challenge(),
            "error": "Wrong or expired captcha answer."},
            status_code=400)

    reason = reason.strip()
    if not reason:
        return templates.TemplateResponse(request, "report.html", {
            "product": product,
            "captcha_token": captcha.new_challenge(),
            "error": "Please select a reason."},
            status_code=400)

    execute(
        "INSERT INTO reports (product_id, reason, description) VALUES (?, ?, ?)",
        (pid, reason, description.strip()))

    return templates.TemplateResponse(request, "report.html", {
        "product": product,
        "captcha_token": captcha.new_challenge(),
        "success": "Report submitted. Thank you for keeping the store safe."})


# --- vendor listing portal (zero-JS, CAPTCHA-protected) ------------------------

@router.get("/sell", response_class=HTMLResponse)
def sell_view(request: Request):
    """Vendor listing submission page."""
    settings_row = query("SELECT * FROM store_settings WHERE id = 1")[0]
    policy = settings_row["listing_policy"] if settings_row else "moderated"
    if policy == "disabled":
        return templates.TemplateResponse(request, "not_found.html",
            {"message": "Public listings are disabled by the store owner."}, status_code=403)
    categories = query("SELECT * FROM categories ORDER BY name COLLATE NOCASE")
    return templates.TemplateResponse(request, "sell.html", {
        "categories": categories,
        "captcha_token": captcha.new_challenge(),
        "policy": policy,
    })


@router.post("/sell")
def sell_submit(request: Request,
                name: str = Form(""), description: str = Form(""),
                price: str = Form("0"), currency: str = Form("USD"),
                category_id: str = Form(""), payout_address: str = Form(""),
                captcha_token: str = Form(""), captcha_answer: str = Form("")):
    """Handle vendor listing submission."""
    settings_row = query("SELECT * FROM store_settings WHERE id = 1")[0]
    policy = settings_row["listing_policy"] if settings_row else "moderated"
    if policy == "disabled":
        return templates.TemplateResponse(request, "not_found.html",
            {"message": "Public listings are disabled by the store owner."}, status_code=403)

    if not captcha.verify(captcha_token, captcha_answer):
        categories = query("SELECT * FROM categories ORDER BY name COLLATE NOCASE")
        return templates.TemplateResponse(request, "sell.html", {
            "categories": categories,
            "captcha_token": captcha.new_challenge(),
            "policy": policy,
            "error": "Wrong or expired captcha answer."},
            status_code=400)

    name = name.strip()[:120]
    if not name:
        categories = query("SELECT * FROM categories ORDER BY name COLLATE NOCASE")
        return templates.TemplateResponse(request, "sell.html", {
            "categories": categories,
            "captcha_token": captcha.new_challenge(),
            "policy": policy,
            "error": "Title is required."},
            status_code=400)

    try:
        price_cents = round(float(price.replace(",", ".")) * 100)
    except ValueError:
        price_cents = 0
    if price_cents < 0:
        price_cents = 0

    currency = (currency or "USD").strip().upper()[:8]

    cat_id = None
    if category_id:
        try:
            cid = int(category_id)
            if query("SELECT id FROM categories WHERE id = ?", (cid,)):
                cat_id = cid
        except ValueError:
            pass

    payout_address = (payout_address or "").strip()

    # Generate unique seller token
    import secrets
    seller_token = secrets.token_hex(16)

    # Determine initial status based on policy
    initial_status = "active" if policy == "open" else "pending_approval"

    listing_id = execute(
        """INSERT INTO seller_listings
           (seller_token, name, description, price_cents, currency, category_id, payout_address, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (seller_token, name, description.strip(), price_cents, currency, cat_id, payout_address, initial_status))

    return templates.TemplateResponse(request, "sell_success.html", {
        "seller_token": seller_token,
        "listing_id": listing_id,
        "status": initial_status,
        "name": name,
    })


# --- seller management via token (no accounts) --------------------------------

@router.get("/sell/manage/{seller_token}", response_class=HTMLResponse)
def sell_manage(request: Request, seller_token: str):
    """Seller dashboard for their listing."""
    listing = query("SELECT * FROM seller_listings WHERE seller_token = ?", (seller_token,))
    if not listing:
        return templates.TemplateResponse(request, "not_found.html", {"message": "Listing not found."}, status_code=404)
    listing = listing[0]

    # Get linked orders
    orders = query("""
        SELECT o.*, sl.name AS listing_name
        FROM seller_orders so
        JOIN orders o ON o.id = so.order_id
        JOIN seller_listings sl ON sl.id = so.seller_listing_id
        WHERE sl.seller_token = ?
        ORDER BY o.created_at DESC
    """, (seller_token,))

    category = None
    if listing["category_id"]:
        rows = query("SELECT * FROM categories WHERE id = ?", (listing["category_id"],))
        category = rows[0] if rows else None

    return templates.TemplateResponse(request, "sell_manage.html", {
        "listing": listing,
        "category": category,
        "orders": orders,
    })


@router.post("/sell/manage/{seller_token}/pause")
def sell_pause(request: Request, seller_token: str):
    """Pause/resume a seller listing."""
    listing = query("SELECT * FROM seller_listings WHERE seller_token = ?", (seller_token,))
    if not listing:
        return RedirectResponse("/sell", status_code=303)
    listing = listing[0]
    new_status = "active" if listing["status"] == "paused" else "paused"
    execute("UPDATE seller_listings SET status = ? WHERE seller_token = ?", (new_status, seller_token))
    return RedirectResponse(f"/sell/manage/{seller_token}", status_code=303)
