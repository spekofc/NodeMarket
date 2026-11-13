"""Admin Visual Customizer: WordPress-style store appearance builder.

Zero-JS, pure HTML forms. All customization compiled to CSS variables
and template variables at render time.
"""

import json
import os
import re
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import captcha
from ..db import query, execute
from ..templating import templates

router = APIRouter(prefix="/admin/customize", tags=["admin-customize"])

UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Allowed image extensions
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

# Preset themes
THEME_PRESETS = {
    "dark": {
        "name": "Tor Dark (Padrão)",
        "bg_color": "#0d0d0d",
        "card_bg_color": "#161616",
        "primary_color": "#e8b450",
        "text_color": "#e8e8e8",
        "border_radius": 8,
        "font_family": "system",
    },
    "green": {
        "name": "Terminal Green (Matrix/Cypherpunk)",
        "bg_color": "#0a0f0a",
        "card_bg_color": "#0d1a0d",
        "primary_color": "#00ff41",
        "text_color": "#b8ffb8",
        "border_radius": 4,
        "font_family": "monospace",
    },
    "light": {
        "name": "Minimal Light (Papel)",
        "bg_color": "#fafafa",
        "card_bg_color": "#ffffff",
        "primary_color": "#2c3e50",
        "text_color": "#2c2c2c",
        "border_radius": 8,
        "font_family": "system",
    },
    "blue": {
        "name": "Midnight Blue",
        "bg_color": "#0a0e1a",
        "card_bg_color": "#111827",
        "primary_color": "#3b82f6",
        "text_color": "#e5e7eb",
        "border_radius": 8,
        "font_family": "system",
    },
    "custom": {
        "name": "Personalizado",
        "bg_color": "#0d0d0d",
        "card_bg_color": "#161616",
        "primary_color": "#e8b450",
        "text_color": "#e8e8e8",
        "border_radius": 8,
        "font_family": "system",
    },
}


def _guard(request: Request) -> Optional[RedirectResponse]:
    """Check admin authentication."""
    from ..security import admin_session_valid, ADMIN_COOKIE
    if not admin_session_valid(request.cookies.get(ADMIN_COOKIE)):
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _strip_exif(image_path: Path) -> bool:
    """Strip EXIF metadata from uploaded image using Pillow if available.
    Returns True if successful, False otherwise.
    """
    try:
        from PIL import Image
        img = Image.open(image_path)
        # Strip EXIF by saving without it
        data = list(img.getdata())
        img_without_exif = Image.new(img.mode, img.size)
        img_without_exif.putdata(data)
        img_without_exif.save(image_path)
        return True
    except Exception:
        return False


def _validate_image(file: UploadFile) -> tuple[bool, str]:
    """Validate uploaded image file."""
    if not file.filename:
        return False, "Nenhum arquivo selecionado."

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return False, f"Formato não suportado. Use: {', '.join(ALLOWED_EXT)}"

    # Check file size by reading content
    content = file.file.read()
    file.file.seek(0)
    if len(content) > MAX_FILE_SIZE:
        return False, f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE // (1024*1024)} MB."

    return True, ""


def _save_upload(file: UploadFile, prefix: str) -> tuple[bool, str, str]:
    """Save uploaded file to static/uploads. Returns (success, path_or_error, filename)."""
    ok, msg = _validate_image(file)
    if not ok:
        return False, msg, ""

    ext = Path(file.filename).suffix.lower()
    filename = f"{prefix}_{secrets.token_hex(8)}{ext}"
    dest = UPLOAD_DIR / filename

    try:
        content = file.file.read()
        dest.write_bytes(content)
        _strip_exif(dest)
        return True, f"uploads/{filename}", filename
    except Exception as e:
        return False, f"Erro ao salvar: {e}", ""


def _get_settings() -> dict:
    """Get store settings as dict."""
    rows = query("SELECT * FROM store_settings WHERE id = 1")
    if rows:
        return dict(rows[0])
    return {}


def _apply_preset(settings: dict, preset: str) -> dict:
    """Apply theme preset to settings dict."""
    if preset in THEME_PRESETS:
        preset_data = THEME_PRESETS[preset]
        for key, value in preset_data.items():
            settings[key] = value
        settings["theme_preset"] = preset
    return settings


# ===== Routes =====

@router.get("", response_class=HTMLResponse)
async def customize_view(request: Request):
    """Main customizer page with all tabs."""
    guard = _guard(request)
    if guard:
        return guard

    settings = _get_settings()

    # Parse nav_items JSON
    nav_items = []
    try:
        nav_items = json.loads(settings.get("nav_items", "[]") or "[]")
    except Exception:
        pass

    # Parse custom_pages JSON
    custom_pages = []
    try:
        custom_pages = json.loads(settings.get("custom_pages", "[]") or "[]")
    except Exception:
        pass

    # Get DB custom pages
    db_pages = query("SELECT * FROM custom_pages WHERE is_published = 1 ORDER BY created_at")

    captcha_token = captcha.new_challenge()

    return templates.TemplateResponse(request, "admin/customize.html", {
        "settings": settings,
        "nav_items": nav_items,
        "custom_pages": custom_pages,
        "db_pages": db_pages,
        "theme_presets": THEME_PRESETS,
        "captcha_token": captcha_token,
        "category_positions": ["top", "left", "right", "hidden"],
        "grid_columns_options": [2, 3, 4],
        "grid_styles": ["grid", "list"],
        "font_families": [
            ("system", "System Sans (Padrão)"),
            ("monospace", "Monospace (Terminal/Hacker)"),
            ("serif", "Editorial Serif"),
        ],
        "theme_preset_options": [(k, v["name"]) for k, v in THEME_PRESETS.items()],
        "category_positions_options": [
            ("top", "Barra Superior (Top Bar)"),
            ("left", "Sidebar Esquerda"),
            ("right", "Sidebar Direita"),
            ("hidden", "Oculto"),
        ],
        "grid_styles_options": [
            ("grid", "Grade (Grid)"),
            ("list", "Lista (List View)"),
        ],
    })


@router.post("/theme")
async def customize_theme(
    request: Request,
    theme_preset: str = Form("dark"),
    bg_color: str = Form(""),
    card_bg_color: str = Form(""),
    primary_color: str = Form(""),
    text_color: str = Form(""),
    border_radius: int = Form(8),
    font_family: str = Form("system"),
    captcha_token: str = Form(""),
    captcha_answer: str = Form(""),
):
    """Apply theme preset or custom colors."""
    guard = _guard(request)
    if guard:
        return guard

    if not captcha.verify(captcha_token, captcha_answer):
        return RedirectResponse("/admin/customize?error=captcha", status_code=303)

    # Apply preset colors if preset is selected (not custom)
    if theme_preset in THEME_PRESETS and theme_preset != "custom":
        preset = THEME_PRESETS[theme_preset]
        bg_color = preset["bg_color"]
        card_bg_color = preset["card_bg_color"]
        primary_color = preset["primary_color"]
        text_color = preset["text_color"]
        border_radius = preset["border_radius"]
        font_family = preset["font_family"]

    execute("""
        UPDATE store_settings SET
            theme_preset = ?, bg_color = ?, card_bg_color = ?,
            primary_color = ?, text_color = ?, border_radius = ?, font_family = ?
        WHERE id = 1
    """, (theme_preset, bg_color, card_bg_color, primary_color, text_color, border_radius, font_family))

    return RedirectResponse("/admin/customize?tab=theme&saved=1", status_code=303)


@router.post("/layout")
async def customize_layout(
    request: Request,
    category_position: str = Form("top"),
    grid_columns: int = Form(3),
    grid_style: str = Form("grid"),
    show_category_badge: int = Form(1),
    show_description: int = Form(1),
    show_add_to_cart: int = Form(1),
    captcha_token: str = Form(""),
    captcha_answer: str = Form(""),
):
    """Save layout settings."""
    guard = _guard(request)
    if guard:
        return guard

    if not captcha.verify(captcha_token, captcha_answer):
        return RedirectResponse("/admin/customize?error=captcha", status_code=303)

    execute("""
        UPDATE store_settings SET
            category_position = ?, grid_columns = ?, grid_style = ?,
            show_category_badge = ?, show_description = ?, show_add_to_cart = ?
        WHERE id = 1
    """, (category_position, grid_columns, grid_style,
          show_category_badge, show_description, show_add_to_cart))

    return RedirectResponse("/admin/customize?tab=layout&saved=1", status_code=303)


@router.post("/identity")
async def customize_identity(
    request: Request,
    store_name: str = Form(""),
    slogan: str = Form(""),
    footer_text: str = Form(""),
    logo_file: UploadFile = File(None),
    banner_file: UploadFile = File(None),
    banner_title: str = Form(""),
    banner_subtitle: str = Form(""),
    banner_button_text: str = Form(""),
    banner_button_url: str = Form(""),
    captcha_token: str = Form(""),
    captcha_answer: str = Form(""),
):
    """Save identity & images."""
    guard = _guard(request)
    if guard:
        return guard

    if not captcha.verify(captcha_token, captcha_answer):
        return RedirectResponse("/admin/customize?error=captcha", status_code=303)

    logo_path = ""
    if logo_file and logo_file.filename:
        ok, path, _ = _save_upload(logo_file, "logo")
        if ok:
            logo_path = path

    banner_path = ""
    if banner_file and banner_file.filename:
        ok, path, _ = _save_upload(banner_file, "banner")
        if ok:
            banner_path = path

    execute("""
        UPDATE store_settings SET
            store_name = ?, banner_title = ?, banner_subtitle = ?,
            banner_button_text = ?, banner_button_url = ?,
            logo_path = ?, banner_path = ?, footer_text = ?
        WHERE id = 1
    """, (store_name.strip(), banner_title.strip(), banner_subtitle.strip(),
          banner_button_text.strip(), banner_button_url.strip(),
          logo_path, banner_path, footer_text.strip()))

    return RedirectResponse("/admin/customize?tab=identity&saved=1", status_code=303)


@router.post("/navigation")
async def customize_navigation(
    request: Request,
    nav_items_json: str = Form(""),
    captcha_token: str = Form(""),
    captcha_answer: str = Form(""),
):
    """Save navigation builder items."""
    guard = _guard(request)
    if guard:
        return guard

    if not captcha.verify(captcha_token, captcha_answer):
        return RedirectResponse("/admin/customize?error=captcha", status_code=303)

    # Validate JSON
    try:
        items = json.loads(nav_items_json) if nav_items_json else []
        # Validate each item
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Invalid item")
            if "label" not in item or "url" not in item:
                raise ValueError("Missing label or url")
    except Exception:
        return RedirectResponse("/admin/customize?tab=navigation&error=invalid_json", status_code=303)

    execute("UPDATE store_settings SET nav_items = ? WHERE id = 1", (json.dumps(items),))

    return RedirectResponse("/admin/customize?tab=navigation&saved=1", status_code=303)


# ===== Custom Pages =====

@router.get("/pages", response_class=HTMLResponse)
async def pages_list(request: Request):
    guard = _guard(request)
    if guard:
        return guard

    pages = query("SELECT * FROM custom_pages ORDER BY created_at DESC")
    return templates.TemplateResponse(request, "admin/pages_list.html", {
        "pages": pages,
    })


@router.get("/pages/new", response_class=HTMLResponse)
async def page_new(request: Request):
    guard = _guard(request)
    if guard:
        return guard

    captcha_token = captcha.new_challenge()
    return templates.TemplateResponse(request, "admin/page_form.html", {
        "page": None,
        "captcha_token": captcha.new_challenge(),
    })


@router.post("/pages/new")
async def page_create(
    request: Request,
    slug: str = Form(""),
    title: str = Form(""),
    content: str = Form(""),
    is_published: int = Form(1),
    captcha_token: str = Form(""),
    captcha_answer: str = Form(""),
):
    guard = _guard(request)
    if guard:
        return guard

    if not captcha.verify(captcha_token, captcha_answer):
        return RedirectResponse("/admin/customize/pages/new?error=captcha", status_code=303)

    slug = slug.strip().lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
    if not slug:
        slug = "page"

    # Check uniqueness
    existing = query("SELECT id FROM custom_pages WHERE slug = ?", (slug,))
    if existing:
        n = 2
        while query("SELECT id FROM custom_pages WHERE slug = ?", (f"{slug}-{n}",)):
            n += 1
        slug = f"{slug}-{n}"

    execute("""
        INSERT INTO custom_pages (slug, title, content, is_published)
        VALUES (?, ?, ?, ?)
    """, (slug, title.strip(), content.strip(), is_published))

    return RedirectResponse("/admin/customize/pages", status_code=303)


@router.get("/pages/{pid}/edit", response_class=HTMLResponse)
async def page_edit(request: Request, pid: int):
    guard = _guard(request)
    if guard:
        return guard

    rows = query("SELECT * FROM custom_pages WHERE id = ?", (pid,))
    if not rows:
        return RedirectResponse("/admin/customize/pages", status_code=303)

    captcha_token = captcha.new_challenge()
    return templates.TemplateResponse(request, "admin/page_form.html", {
        "page": dict(rows[0]),
        "captcha_token": captcha.new_challenge(),
    })


@router.post("/pages/{pid}/edit")
async def page_update(
    request: Request,
    pid: int,
    slug: str = Form(""),
    title: str = Form(""),
    content: str = Form(""),
    is_published: int = Form(1),
    captcha_token: str = Form(""),
    captcha_answer: str = Form(""),
):
    guard = _guard(request)
    if guard:
        return guard

    if not captcha.verify(captcha_token, captcha_answer):
        return RedirectResponse(f"/admin/customize/pages/{pid}/edit?error=captcha", status_code=303)

    slug = slug.strip().lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
    if not slug:
        slug = "page"

    # Check uniqueness (excluding current page)
    existing = query("SELECT id FROM custom_pages WHERE slug = ? AND id != ?", (slug, pid))
    if existing:
        n = 2
        while query("SELECT id FROM custom_pages WHERE slug = ? AND id != ?", (f"{slug}-{n}", pid)):
            n += 1
        slug = f"{slug}-{n}"

    execute("""
        UPDATE custom_pages SET
            slug = ?, title = ?, content = ?, is_published = ?,
            updated_at = datetime('now')
        WHERE id = ?
    """, (slug, title.strip(), content.strip(), is_published, pid))

    return RedirectResponse("/admin/customize/pages", status_code=303)


@router.post("/pages/{pid}/delete")
async def page_delete(request: Request, pid: int):
    guard = _guard(request)
    if guard:
        return guard

    execute("DELETE FROM custom_pages WHERE id = ?", (pid,))
    return RedirectResponse("/admin/customize/pages", status_code=303)