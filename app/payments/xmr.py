"""Monero payment provider.

Three configuration paths (set in /admin/settings):

- main address (direct): one static address for every order. Simple,
  but orders are linkable on-chain - prefer subaddress rotation.
- subaddress rotation (direct): the admin pastes a list of subaddresses;
  each order gets ``list[order_id % len(list)]``. Per-order addresses
  without any server-side wallet. Non-custodial.
- wallet RPC: the local monero-wallet-rpc generates a dedicated
  subaddress per order (``create_address``). Keys live on the server -
  pair with Temporary Escrow settlement.

Privacy note: Monero amounts are hidden on-chain; the fiat-equivalent
line is informational only and uses the manual rate set by the admin
(never a third-party price API).
"""

from .base import PaymentProvider, register
from . import rpc


def _parse_subaddresses(raw: str) -> list[str]:
    out = []
    for chunk in (raw or "").replace("\n", ",").replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            out.append(chunk)
    return out


def _crypto_amount_line(rate_text: str, total_cents: int, currency: str) -> str:
    rate_text = (rate_text or "").strip()
    if not rate_text:
        return (f"Order total: {total_cents / 100:.2f} {currency} "
                f"(pay the equivalent at the current market rate)")
    try:
        rate = float(rate_text)
        if rate <= 0:
            raise ValueError
    except ValueError:
        return (f"Order total: {total_cents / 100:.2f} {currency} "
                f"(invalid exchange rate configured - contact the store)")
    amount = (total_cents / 100) * rate
    return (f"Order total: {total_cents / 100:.2f} {currency} "
            f"= {amount:.6f} XMR (manual rate - verify before sending)")


class XmrProvider(PaymentProvider):
    name = "xmr"
    label = "Monero (XMR)"
    requires_settings = True

    def create_payment(self, order_id, total_cents, currency, store_settings):
        escrow = (store_settings.get("settlement_mode") or "direct") == "escrow"

        subaddresses = _parse_subaddresses(store_settings.get("xmr_subaddresses", ""))
        if subaddresses:
            # Direct, non-custodial: rotate through admin-provided subaddresses.
            address = subaddresses[order_id % len(subaddresses)]
            custody = ("This subaddress belongs to the seller's own wallet - "
                       "this server never holds private keys.")
            uniqueness = f"Subaddress {order_id % len(subaddresses) + 1}/{len(subaddresses)}"
        else:
            main_address = (store_settings.get("xmr_address") or "").strip()
            if main_address:
                address = main_address
                custody = ("Funds arrive in the store's main Monero address."
                           + (" Payment is held in escrow until you confirm "
                              "receipt." if escrow else ""))
                uniqueness = "Shared store address"
            else:
                # Last resort: wallet RPC (custodial) - only if configured.
                try:
                    address = rpc.xmr_new_address(f"nodemarket-order-{order_id}")
                except (rpc.RPCError, OSError) as exc:
                    return ("Monero payment is misconfigured: no address and "
                            f"no wallet RPC available. ({exc})")
                custody = ("Funds arrive in the node wallet configured by the "
                           "store." + (" Payment is held in escrow until you "
                                       "confirm receipt." if escrow else ""))
                uniqueness = f"Dedicated subaddress for order #{order_id}"

        lines = [
            "Send the payment to this Monero address:",
            f"{uniqueness}: {address}",
            _crypto_amount_line(store_settings.get("xmr_rate"), total_cents,
                                currency),
            custody,
        ]
        if escrow:
            lines.append("Track and release the payment on your order page "
                         "after delivery is confirmed.")
        return "\n".join(lines)


register(XmrProvider())
