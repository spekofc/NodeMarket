"""Bitcoin payment provider.

Two configuration paths (set in /admin/settings):

- ``xpub`` mode (non-custodial default): a unique native-SegWit P2WPKH
  address is derived per order from the store's account-level extended
  public key via BIP32 public derivation (see xpub.py, pure stdlib).
  The server never sees a private key - funds land directly in the
  seller's external wallet.
- ``rpc`` mode: the local Bitcoin Core node hands out an address from
  its own wallet (``getnewaddress``). Keys live on the node - pair this
  with Temporary Escrow settlement, where the node acts as custodian.

No network calls happen in xpub mode. RPC mode talks only to the node
configured in .env. Fiat->BTC conversion is never fetched online: the
admin sets a manual rate or the buyer pays the stated fiat equivalent
at market rate.
"""

from .base import PaymentProvider, register
from . import rpc
from .xpub import derive_address


def _crypto_amount_line(rate_text: str, total_cents: int,
                        currency: str, decimals: int) -> str:
    """Manual exchange-rate line, or a fallback note when unset."""
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
            f"= {amount:.{decimals}f} BTC (manual rate - verify before sending)")


class BtcProvider(PaymentProvider):
    name = "btc"
    label = "Bitcoin (BTC)"
    requires_settings = True

    def create_payment(self, order_id, total_cents, currency, store_settings):
        mode = (store_settings.get("btc_mode") or "xpub").strip()
        escrow = (store_settings.get("settlement_mode") or "direct") == "escrow"
        try:
            if mode == "rpc":
                address = rpc.btc_new_address(f"nodemarket-order-{order_id}")
                custody = ("Funds arrive in the node wallet configured by the "
                           "store." + (" Payment is held in escrow until you "
                                       "confirm receipt." if escrow else ""))
            else:
                xpub = (store_settings.get("xpub") or "").strip()
                if not xpub:
                    return ("Bitcoin payment is misconfigured: no xpub set in "
                            "admin settings. Contact the store.")
                address = derive_address(xpub, order_id)
                custody = ("This address belongs to the seller's own wallet - "
                           "this server never holds private keys."
                           + (" Payment is held in escrow until you confirm "
                              "receipt." if escrow else ""))
        except (rpc.RPCError, ValueError, OSError) as exc:
            return f"Bitcoin payment error: {exc}"

        lines = [
            "Send the payment to this Bitcoin address "
            f"(unique for order #{order_id}):",
            address,
            _crypto_amount_line(store_settings.get("btc_rate"), total_cents,
                                currency, 8),
            custody,
        ]
        if escrow:
            lines.append("Track and release the payment on your order page "
                         "after delivery is confirmed.")
        return "\n".join(lines)


register(BtcProvider())
