"""Jinja2 environment shared by all routers."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# money helper: cents -> "12.34"
templates.env.filters["money"] = lambda cents: f"{cents / 100:.2f}"
