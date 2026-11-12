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
    """SQLite LIKE search over title/description, optional category filter."""
    sql = "SELECT * FROM products WHERE active = 1"
    params: list = []
    if category_id is not None:
        sql += " AND category_id = ?"
        params.append(category_id)
    if term:
        sql += " AND (name LIKE ? OR description LIKE ?)"
        like = f"%{term}%"
        params += [like, like]
    sql += " ORDER BY created_at DESC"
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


@router.get("/product/{pid}", response_class=HTMLResponse)
def product_detail(request: Request, pid: int):
    product = _product_or_none(pid)
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
