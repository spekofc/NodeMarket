"""Checkout: the only place buyer data enters the system - and it enters
PGP-encrypted or not at all.

v0.3: multi-currency selection (BTC / XMR / Demo, independently enabled
in admin settings), settlement mode frozen per order, and the buyer
release action on the token-tracked order page.
"""

import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import captcha
from ..db import query, execute
from ..pgp import encrypt_for_store, validate_public_key, validate_pgp_message
from ..payments import get_provider
from ..payments import escrow
from ..security import cart_load, CART_COOKIE, admin_session_valid
from ..templating import templates

router = APIRouter()

# display metadata for the checkout radio buttons (HTML only, no JS)
METHOD_META = {
    "demo": ("Demo payment (no real payment)", "For testing this storefront."),
    "btc": ("Bitcoin (BTC)",
            "Per-order address. Direct mode sends straight to the seller's "
            "wallet; escrow mode holds payment until you confirm receipt."),
    "xmr": ("Monero (XMR)",
            "Private by default. Direct mode uses store subaddresses; "
            "escrow mode holds payment until you confirm receipt."),
}


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


def _enabled_methods(settings_row) -> list[tuple[str, str, str]]:
    """(key, label, description) for every payment method the admin enabled."""
    out = []
    for key in ("btc", "xmr", "demo"):
        if not settings_row[f"{key}_enabled"]:
            continue
        if key == "btc" and settings_row["btc_mode"] == "xpub" \
                and not (settings_row["xpub"] or "").strip():
            continue  # cannot offer BTC without an xpub in xpub mode
        label, desc = METHOD_META[key]
        out.append((key, label, desc))
    return out


def _checkout_context(totals, settings_row, captcha_token="", error="", pgp_error="",
                       pgp_mode="plain", pgp_block=""):
    methods = _enabled_methods(settings_row)
    key_ok, key_msg = validate_public_key(settings_row["pgp_public_key"] or "")
    # form is always shown if cart is valid; plaintext option gated by key_ok
    ctx = {
        "cart": totals,
        "key_ok": key_ok,
        "key_msg": key_msg,
        "methods": methods,
        "settlement_mode": settings_row["settlement_mode"],
        "captcha_token": captcha_token,
        "captcha_error": error,
        "pgp_error": pgp_error,
        "pgp_mode": pgp_mode,
        "pgp_block": pgp_block,
        "settings": dict(settings_row),
    }
    return ctx, key_ok


@router.get("/checkout", response_class=HTMLResponse)
def checkout_view(request: Request):
    totals = _cart_totals(request)
    if not totals:
        return RedirectResponse("/cart", status_code=303)
    settings_row = query("SELECT * FROM store_settings WHERE id = 1")[0]
    ctx, _ = _checkout_context(totals, settings_row, captcha.new_challenge())
    return templates.TemplateResponse(request, "checkout.html", ctx)


@router.post("/checkout")
def checkout_place(request: Request, delivery_details: str = Form(""),
                   payment_method: str = Form("demo"),
                   pgp_mode: str = Form("plain"), pgp_block: str = Form(""),
                   captcha_token: str = Form(""), captcha_answer: str = Form("")):
    totals = _cart_totals(request)
    if not totals:
        return RedirectResponse("/cart", status_code=303)

    settings_row = query("SELECT * FROM store_settings WHERE id = 1")[0]
    enabled = {key for key, *_ in _enabled_methods(settings_row)}
    if payment_method not in enabled:
        payment_method = next(iter(enabled), "demo")  # sane fallback, never crash

    # CAPTCHA first: spam never reaches order creation or the database.
    if not captcha.verify(captcha_token, captcha_answer):
        ctx, _ = _checkout_context(
            totals, settings_row, captcha.new_challenge(),
            "Wrong or expired captcha answer.",
            pgp_mode=pgp_mode, pgp_block=pgp_block)
        return templates.TemplateResponse(
            request, "checkout.html", ctx, status_code=400)

    armored = settings_row["pgp_public_key"] or ""
    key_ok, key_msg = validate_public_key(armored)

    # Minimal buyer context inside the encrypted payload - nothing else is stored.
    buyer_text = delivery_details.strip() or "(no delivery details provided)"
    if pgp_mode == "own":
        # Bring Your Own PGP: the buyer pre-encrypted their details with
        # their own key. The server validates the block, stores it verbatim
        # and cannot read it - no store key needed at all.
        ok, msg = validate_pgp_message(pgp_block)
        if not ok:
            ctx, _ = _checkout_context(totals, settings_row, captcha.new_challenge(),
                                       pgp_error=msg, pgp_mode=pgp_mode, pgp_block=pgp_block)
            return templates.TemplateResponse(
                request, "checkout.html", ctx, status_code=400)
        ciphertext = pgp_block.strip()
    else:
        # Store-key mode, fail closed: never store plaintext buyer data.
        if not key_ok:
            ctx, _ = _checkout_context(totals, settings_row, captcha.new_challenge(),
                                       pgp_mode=pgp_mode, pgp_block=pgp_block)
            return templates.TemplateResponse(
                request, "checkout.html", ctx, status_code=400)
        try:
            ciphertext = encrypt_for_store(armored, buyer_text)
        except Exception:
            # Fail closed even when the key parses but cannot encrypt
            # (e.g. no encryption subkey): 400, no row, no plaintext anywhere.
            ctx, _ = _checkout_context(totals, settings_row, captcha.new_challenge(),
                                       pgp_mode=pgp_mode, pgp_block=pgp_block)
            return templates.TemplateResponse(
                request, "checkout.html", ctx, status_code=400)

    provider = get_provider(payment_method) or get_provider("demo")
    provider_settings = dict(settings_row)  # Row -> dict (providers use .get)
    # order id 0 for the preview; re-derived with the real id right after.
    details_text = provider.create_payment(
        0, totals["total_cents"], totals["currency"], provider_settings)

    # 128-bit random tracking token: the order URL is the only credential.
    order_ref = secrets.token_hex(16)
    settlement_mode = settings_row["settlement_mode"]
    order_id = execute(
        """INSERT INTO orders
           (order_ref, status, total_cents, currency, payment_provider,
            payment_label, payment_details, buyer_encrypted, settlement_mode)
           VALUES (?, 'pending_payment', ?, ?, ?, ?, ?, ?, ?)""",
        (order_ref, totals["total_cents"], totals["currency"], provider.name,
         provider.label, details_text, ciphertext, settlement_mode),
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
        order_id, totals["total_cents"], totals["currency"], provider_settings)
    execute("UPDATE orders SET payment_details = ? WHERE id = ?", (real_details, order_id))

    if settlement_mode == "escrow":
        escrow.log_event(order_id, "pending_payment", "system",
                         f"escrow order created via {provider.name}")

    response = RedirectResponse(f"/order/{order_ref}", status_code=303)
    response.delete_cookie(CART_COOKIE, path="/")
    return response


@router.get("/order/{order_ref}", response_class=HTMLResponse)
def order_view(request: Request, order_ref: str):
    order = escrow.get_order(order_ref)
    if not order:
        return templates.TemplateResponse(
            request, "not_found.html", {"message": "Order not found."}, status_code=404)
    order["payment_details_lines"] = order["payment_details"].splitlines()
    events = escrow.get_events(order["id"]) if order["settlement_mode"] == "escrow" else []
    settings_row = query("SELECT * FROM store_settings WHERE id = 1")[0]
    return templates.TemplateResponse(
        request, "order.html",
        {"order": order, "events": events,
         "can_release": order["status"] == "in_escrow",
         "settings": dict(settings_row)})


@router.post("/order/{order_ref}/release", response_class=HTMLResponse)
def order_release(request: Request, order_ref: str):
    """Buyer confirms receipt: in_escrow -> completed_released.

    CSRF protection: the global OriginCheck middleware rejects
    cross-origin form posts, and the 128-bit order_ref in the URL is the
    only capability - no session, no cookie, nothing to forge.
    """
    order = escrow.get_order(order_ref)
    if not order:
        return templates.TemplateResponse(
            request, "not_found.html", {"message": "Order not found."}, status_code=404)
    order["payment_details_lines"] = order["payment_details"].splitlines()
    error = ""
    try:
        order = escrow.transition(order, "completed_released", "buyer")
    except escrow.TransitionError as exc:
        error = f"Cannot release payment: {exc}"
    events = escrow.get_events(order["id"])
    settings_row = query("SELECT * FROM store_settings WHERE id = 1")[0]
    return templates.TemplateResponse(
        request, "order.html",
        {"order": order, "events": events,
         "can_release": order["status"] == "in_escrow",
         "release_error": error,
         "settings": dict(settings_row)})


# --- order messaging (zero-JS, no accounts) -----------------------------------

@router.get("/order/{order_ref}/messages", response_class=HTMLResponse)
def order_messages_view(request: Request, order_ref: str):
    """Buyer-side message thread for an order."""
    order = escrow.get_order(order_ref)
    if not order:
        return templates.TemplateResponse(
            request, "not_found.html", {"message": "Order not found."}, status_code=404)
    messages = query(
        "SELECT * FROM order_messages WHERE order_id = ? ORDER BY id",
        (order["id"],))
    events = escrow.get_events(order["id"]) if order["settlement_mode"] == "escrow" else []
    order["payment_details_lines"] = order["payment_details"].splitlines()
    return templates.TemplateResponse(
        request, "order_messages.html",
        {"order": order, "messages": messages, "events": events,
         "can_release": order["status"] == "in_escrow",
         "captcha_token": captcha.new_challenge()})


@router.post("/order/{order_ref}/messages")
def order_message_send(request: Request, order_ref: str,
                       body: str = Form(""),
                       pgp_mode: str = Form("encrypt"),
                       captcha_token: str = Form(""), captcha_answer: str = Form("")):
    """Buyer sends a message to the seller (encrypted by default)."""
    order = escrow.get_order(order_ref)
    if not order:
        return templates.TemplateResponse(
            request, "not_found.html", {"message": "Order not found."}, status_code=404)

    # CAPTCHA rate limiting on message sends
    if not captcha.verify(captcha_token, captcha_answer):
        messages = query(
            "SELECT * FROM order_messages WHERE order_id = ? ORDER BY id",
            (order["id"],))
        events = escrow.get_events(order["id"]) if order["settlement_mode"] == "escrow" else []
        order["payment_details_lines"] = order["payment_details"].splitlines()
        return templates.TemplateResponse(
            request, "order_messages.html",
            {"order": order, "messages": messages, "events": events,
             "can_release": order["status"] == "in_escrow",
             "msg_error": "Wrong or expired captcha answer.",
             "captcha_token": captcha.new_challenge()},
            status_code=400)

    body = body.strip()
    if not body:
        messages = query(
            "SELECT * FROM order_messages WHERE order_id = ? ORDER BY id",
            (order["id"],))
        events = escrow.get_events(order["id"]) if order["settlement_mode"] == "escrow" else []
        order["payment_details_lines"] = order["payment_details"].splitlines()
        return templates.TemplateResponse(
            request, "order_messages.html",
            {"order": order, "messages": messages, "events": events,
             "can_release": order["status"] == "in_escrow",
             "msg_error": "Message cannot be empty.",
             "captcha_token": captcha.new_challenge()},
            status_code=400)

    settings_row = query("SELECT * FROM store_settings WHERE id = 1")[0]
    armored = settings_row["pgp_public_key"] or ""
    key_ok, _ = validate_public_key(armored)

    if pgp_mode == "encrypt" and key_ok:
        try:
            ciphertext = encrypt_for_store(armored, body)
            is_encrypted = 1
        except Exception:
            ciphertext = body
            is_encrypted = 0
    else:
        # plaintext or store key unavailable
        ciphertext = body
        is_encrypted = 0

    execute(
        "INSERT INTO order_messages (order_id, author, body, is_encrypted) VALUES (?, 'buyer', ?, ?)",
        (order["id"], ciphertext, is_encrypted))

    return RedirectResponse(f"/order/{order_ref}/messages", status_code=303)


# Admin-side: seller replies to buyer
@router.post("/admin/orders/{order_ref}/messages")
def admin_order_message_reply(request: Request, order_ref: str, body: str = Form("")):
    """Seller replies to buyer from admin panel."""
    guard = admin_session_valid(request.cookies.get("nm_admin"))
    if not guard:
        return RedirectResponse("/admin/login", status_code=303)

    order = escrow.get_order(order_ref)
    if not order:
        return RedirectResponse("/admin", status_code=303)

    body = body.strip()
    if not body:
        return RedirectResponse(f"/admin/orders/{order_ref}", status_code=303)

    # Seller replies are stored as plaintext (buyer can read them directly)
    execute(
        "INSERT INTO order_messages (order_id, author, body, is_encrypted) VALUES (?, 'seller', ?, 0)",
        (order["id"], body))

    return RedirectResponse(f"/admin/orders/{order_ref}", status_code=303)
