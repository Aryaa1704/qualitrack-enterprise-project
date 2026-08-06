"""Shared template configuration for HTML pages."""

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"


def static_asset_url(request: Request, path: str) -> str:
    """Return a host-relative static asset URL that works behind reverse proxies."""

    normalized_path = path.lstrip("/")
    root_path = request.scope.get("root_path", "").rstrip("/")
    return f"{root_path}/static/{normalized_path}"


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["static_url"] = static_asset_url
