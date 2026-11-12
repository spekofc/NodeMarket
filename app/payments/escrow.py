"""EscrowEngine - lifecycle of Temporary Escrow settlement.

State machines (per order, frozen at checkout):

Direct-to-Seller (non-custodial, default):
    pending_payment -> paid -> completed
                    -> cancelled (before completion)
    The address belongs to the seller's external wallet; the server
    never moves funds. Status here is bookkeeping only.

Temporary Escrow (custodial until confirmation):
    pending_payment -> in_escrow -> completed_released
                                -> disputed -> completed_released
                    -> cancelled
    Funds sit in the custodian wallet (RPC-configured node). Release
    happens when the buyer confirms receipt, or the admin resolves a
    dispute. On release the engine fires an auto-payout hook that
    sweeps the custodian balance to the configured payout address via
    local RPC; if RPC is not connected the event log records the
    pending manual payout and the admin handles it from their wallet.

All transitions are validated: an illegal move raises TransitionError
instead of silently corrupting the order lifecycle.
"""

from . import rpc
from ..db import query, execute

TRANSITIONS = {
    "direct": {
        "pending_payment": {"paid", "cancelled"},
        "paid": {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    },
    "escrow": {
        "pending_payment": {"in_escrow", "cancelled"},
        "in_escrow": {"completed_released", "disputed"},
        "disputed": {"completed_released", "cancelled"},
        "completed_released": set(),
        "cancelled": set(),
    },
}

# States the buyer may reach from the order tracking page.
BUYER_ALLOWED = {("in_escrow", "completed_released")}


class TransitionError(ValueError):
    pass


def get_order(order_ref: str) -> dict | None:
    rows = query("SELECT * FROM orders WHERE order_ref = ?", (order_ref,))
    return dict(rows[0]) if rows else None


def get_events(order_id: int) -> list:
    return query(
        """SELECT event, actor, note, created_at FROM escrow_events
           WHERE order_id = ? ORDER BY id ASC""", (order_id,))


def log_event(order_id: int, event: str, actor: str, note: str = "") -> None:
    execute(
        """INSERT INTO escrow_events (order_id, event, actor, note)
           VALUES (?, ?, ?, ?)""",
        (order_id, event, actor, note),
    )


def can_transition(order: dict, to_state: str, actor: str) -> bool:
    mode = order.get("settlement_mode", "direct")
    allowed = TRANSITIONS.get(mode, {}).get(order["status"], set())
    if to_state not in allowed:
        return False
    if actor == "buyer":
        return (order["status"], to_state) in BUYER_ALLOWED
    return True


def transition(order: dict, to_state: str, actor: str, note: str = "") -> dict:
    """Validate + apply a state change, log it, and fire release hooks.

    `order` must be a row dict from get_order(); the caller re-reads
    afterwards if it needs the fresh status.
    """
    if not can_transition(order, to_state, actor):
        raise TransitionError(
            f"illegal transition {order['status']} -> {to_state} "
            f"(mode={order.get('settlement_mode')}, actor={actor})")

    execute("UPDATE orders SET status = ? WHERE id = ?",
            (to_state, order["id"]))
    log_event(order["id"], to_state, actor, note)

    if to_state == "completed_released":
        hook_note = _on_released(order)
        if hook_note:
            log_event(order["id"], "payout_hook", "system", hook_note)

    fresh = get_order(order["order_ref"])
    return fresh if fresh else order


def _on_released(order: dict) -> str:
    """Auto-payout hook: sweep custodian balance to the payout address.

    Returns a human-readable note recorded in the event log. Never
    raises - a failed RPC must not corrupt the released state; the note
    tells the admin to pay out manually.
    """
    settings_row = query("SELECT payout_btc_address, payout_xmr_address "
                         "FROM store_settings WHERE id = 1")[0]
    if order["payment_provider"] == "btc":
        destination = (settings_row["payout_btc_address"] or "").strip()
        if not destination:
            return "escrow released - no payout address configured; pay out manually"
        try:
            result = rpc.btc_sweep_all(destination)
            txid = result[0] if isinstance(result, list) else result
            return f"escrow released - auto payout sent: {txid}"
        except (rpc.RPCError, OSError, KeyError, ValueError) as exc:
            return (f"escrow released - auto payout FAILED ({exc}); "
                    f"sweep manually to {destination}")
    if order["payment_provider"] == "xmr":
        destination = (settings_row["payout_xmr_address"] or "").strip()
        if not destination:
            return "escrow released - no payout address configured; pay out manually"
        try:
            result = rpc.xmr_sweep_all(destination)
            tx_hash = (result.get("tx_hash_list") or ["?"])[0]
            return f"escrow released - auto payout sent: {tx_hash}"
        except (rpc.RPCError, OSError, KeyError, ValueError) as exc:
            return (f"escrow released - auto payout FAILED ({exc}); "
                    f"sweep manually to {destination}")
    # demo / xpub / legacy providers: nothing to sweep.
    return "escrow released - demo/legacy provider, no payout hook"
