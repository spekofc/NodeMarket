"""Demo payment provider: clean, no network, no wallet required."""

from .base import PaymentProvider, register


class DemoProvider(PaymentProvider):
    name = "demo"
    label = "Demo payment (no real payment required)"

    def create_payment(self, order_id, total_cents, currency, store_settings):
        amount = f"{total_cents / 100:.2f}"
        return (
            f"This order was placed on a demonstration storefront.\n"
            f"Amount: {amount} {currency} (not collected).\n"
            f"The store owner marks orders as paid from the admin panel."
        )


register(DemoProvider())
