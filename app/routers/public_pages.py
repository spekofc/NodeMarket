"""Public pages router (no admin prefix)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..db import query
from ..templating import templates

router = APIRouter()


@router.get("/page/{slug}", response_class=HTMLResponse)
async def page_view(request: Request, slug: str):
    """Public view of a custom page."""
    rows = query("SELECT * FROM custom_pages WHERE slug = ? AND is_published = 1", (slug,))
    if not rows:
        return templates.TemplateResponse(request, "not_found.html", {"message": "Página não encontrada."}, status_code=404)

    page = dict(rows[0])
    settings_row = query("SELECT * FROM store_settings WHERE id = 1")[0]
    return templates.TemplateResponse(request, "page_custom.html", {"page": page, "settings": dict(settings_row)})