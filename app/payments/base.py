"""NodeMarket payment abstraction.

A PaymentProvider takes an order and the store settings and returns a
human-readable payment label + details string shown to the buyer.
Confirmation of payment is manual by the store owner (admin panel) for
every provider: no payment callbacks, no webhooks, no third-party calls.
"""

from typing import Callable

from ..db import query, execute  # noqa: F401  (re-exported for providers)

providers: dict[str, "PaymentProvider"] = {}


class PaymentProvider:
    name: str = ""
    label: str = ""
    requires_settings: bool = False

    def create_payment(self, order_id: int, total_cents: int,
                       currency: str, store_settings: dict) -> str:
        """Return details text for the buyer. Must not touch the network."""
        raise NotImplementedError


def register(provider: PaymentProvider) -> None:
    providers[provider.name] = provider


def get_provider(name: str) -> PaymentProvider | None:
    return providers.get(name)


def available() -> list[str]:
    return sorted(providers)
