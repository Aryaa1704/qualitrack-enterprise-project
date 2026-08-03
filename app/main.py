"""FastAPI application entry point for QualiTrack."""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description=settings.app_description,
    version=settings.app_version,
    debug=settings.debug,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse, tags=["Pages"])
def home(request: Request) -> HTMLResponse:
    """Render the public home page."""

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
        },
    )


@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    """Return a simple health status for uptime checks."""

    return {"status": "ok", "service": settings.app_name}
