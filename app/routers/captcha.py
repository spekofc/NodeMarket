"""CAPTCHA image endpoint: serves the challenge SVG from the same origin."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from .. import captcha
from ..templating import templates

router = APIRouter()


@router.get("/captcha.svg")
def captcha_svg(token: str):
    svg = captcha.render_svg(token)
    if svg is None:
        return HTMLResponse("Unknown or expired captcha token.", status_code=404)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )
