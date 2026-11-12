"""Payment provider registry. Importing submodules registers the built-ins."""

from .base import PaymentProvider, register, get_provider, available  # noqa: F401
from . import demo, xpub, btc, xmr  # noqa: F401
