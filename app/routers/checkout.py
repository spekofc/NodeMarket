"""Checkout: the only place buyer data enters the system - and it enters
PGP-encrypted or not at all.
"""

import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import captcha
from ..db import query, execute
from ..pgp import encrypt_for_store, validate_public_key
from ..payments import get_provider
from ..security import cart_load, CART_COOKIE
from ..templating import templates

router = APIRouter()


def _cart_totals(request: Request):
    cart_raw = cart_load(request.cookies.get("nm_cart", ""))
    if not cart_raw:
        return None
    placeholders = ",".join("?" * len(cart_raw))
    rows = query(
        f"SELECT * FROM products WHERE id IN ({placeholders}) AND active = 1",
        tuple(cart_raw.keys()),
    )
    if not rows:
        return None
    items, total_cents, currency = [], 0, rows[0]["currency"]
    for row in rows:
        qty = cart_raw[row["id"]]
        items.append((row["id"], row["name"], qty, row["price_cents"]))
        total_cents += qty * row["price_cents"]
    return {"items": items, "total_cents": total_cents, "currency": currency}


@router.get("/checkout", response_class=HTMLResponse)
def checkout_view(request: Request):
    totals = _cart_totals(request)
    if not totals:
        return RedirectResponse("/cart", status_code=303)
    settings_row = query("SELECT pgp_public_key, payment_provider FROM store_settings WHERE id = 1")[0]
    key_ok, key_msg = validate_public_key(settings_row["pgp_public_key"] or "")
    token = captcha.new_challenge() if key_ok else ""
    return templates.TemplateResponse(request, "checkout.html", {
        "cart": totals,
        "key_ok": key_ok,
        "key_msg": key_msg,
        "provider_name": settings_row["payment_provider"],
        "captcha_token": token,
    })


@router.post("/checkout")
def checkout_place(request: Request, delivery_details: str = Form(""),
                   captcha_token: str = Form(""), captcha_answer: str = Form("")):
    totals = _cart_totals(request)
    if not totals:
        return RedirectResponse("/cart", status_code=303)

    # CAPTCHA first: spam never reaches order creation or the database.
    if not captcha.verify(captcha_token, captcha_answer):
        settings_row = query(
            "SELECT pgp_public_key, payment_provider FROM store_settings WHERE id = 1"
        )[0]
        ok, msg = validate_public_key(settings_row["pgp_public_key"] or "")
        return templates.TemplateResponse(
            request, "checkout.html",
            {"cart": totals, "key_ok": ok, "key_msg": msg,
             "provider_name": settings_row["payment_provider"],
             "captcha_token": captcha.new_challenge() if ok else "",
             "captcha_error": "Wrong or expired captcha answer."},
            status_code=400,
        )

    settings_row = query(
        "SELECT pgp_public_key, payment_provider FROM store_settings WHERE id = 1"
    )[0]
    armored = settings_row["pgp_public_key"] or ""
    ok, msg = validate_public_key(armored)
    if not ok:
        # Fail closed: never store plaintext buyer data.
        return templates.TemplateResponse(
            request, "checkout.html",
            {"cart": totals, "key_ok": False, "key_msg": msg,
             "provider_name": settings_row["payment_provider"]},
            status_code=400,
        )

    # Minimal buyer context inside the encrypted payload - nothing else is stored.
    buyer_text = delivery_details.strip() or "(no delivery details provided)"
    ciphertext = encrypt_for_store(armored, buyer_text)

    provider = get_provider(settings_row["payment_provider"]) or get_provider("demo")
    store_settings = {
        "xpub": (query("SELECT xpub FROM store_settings WHERE id = 1")[0]["xpub"] or ""),
    }
    details_text = provider.create_payment(
        0, totals["total_cents"], totals["currency"], store_settings
    )

    order_ref = secrets.token_hex(8)
    order_id = execute(
        """INSERT INTO orders
           (order_ref, total_cents, currency, payment_provider,
            payment_label, payment_details, buyer_encrypted)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (order_ref, totals["total_cents"], totals["currency"], provider.name,
         provider.label, details_text, ciphertext),
    )
    for pid, name, qty, price in totals["items"]:
        execute(
            """INSERT INTO order_items
               (order_id, product_id, name_snapshot, qty, unit_price_cents)
               VALUES (?, ?, ?, ?, ?)""",
            (order_id, pid, name, qty, price),
        )

    # Recreate payment details with the real order id (derivation index).
    real_details = provider.create_payment(
        order_id, totals["total_cents"], totals["currency"], store_settings
    )
    execute("UPDATE orders SET payment_details = ? WHERE id = ?", (real_details, order_id))

    response = RedirectResponse(f"/order/{order_ref}", status_code=303)
    response.delete_cookie(CART_COOKIE, path="/")
    return response


@router.get("/order/{order_ref}", response_class=HTMLResponse)
def order_view(request: Request, order_ref: str):
    rows = query("SELECT * FROM orders WHERE order_ref = ?", (order_ref,))
    if not rows:
        return templates.TemplateResponse(request, "not_found.html", {"message": "Order not found."}, status_code=404)
    order = dict(rows[0])
    order["payment_details_lines"] = order["payment_details"].splitlines()
    return templates.TemplateResponse(request, "order.html", {"order": order})
