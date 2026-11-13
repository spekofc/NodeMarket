"""Jinja2 environment shared by all routers.

`base.html` reads store settings (CSS variables, banner, footer) from a
`settings` context variable. Rather than trust every route to pass it,
the template wrapper injects the current row automatically. Routes that
already pass `settings` keep their own value untouched.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from .db import query

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class NodeMarketTemplates(Jinja2Templates):
    """Jinja2Templates that guarantees `settings` and `store_name` exist."""

    @staticmethod
    def _inject(context: dict | None) -> dict:
        ctx = dict(context or {})
        if "settings" not in ctx:
            rows = query("SELECT * FROM store_settings WHERE id = 1")
            ctx["settings"] = dict(rows[0]) if rows else {}
        if "store_name" not in ctx:
            ctx["store_name"] = ctx["settings"].get("store_name") or "NodeMarket"
        return ctx

    def TemplateResponse(self, *args, **kwargs):
        # New style: (request, name, context, ...) — used across this project.
        if args and hasattr(args[0], "scope"):
            request, name, *rest = args
            context = rest[0] if rest else kwargs.pop("context", None)
            rest = rest[1:]
            return super().TemplateResponse(
                request, name, self._inject(context), *rest, **kwargs
            )
        # Old style: (name, context, ...).
        name, *rest = args
        context = rest[0] if rest else kwargs.pop("context", None)
        rest = rest[1:]
        return super().TemplateResponse(name, self._inject(context), *rest, **kwargs)


templates = NodeMarketTemplates(directory=str(TEMPLATES_DIR))

# money helper: cents -> "12.34"
templates.env.filters["money"] = lambda cents: f"{cents / 100:.2f}"
