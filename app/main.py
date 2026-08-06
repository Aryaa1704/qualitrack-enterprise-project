"""FastAPI application entry point for QualiTrack."""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.database.session import get_db
from app.routers.auth import get_optional_current_user, router as auth_router
from app.routers.batches import router as batches_router
from app.routers.defects import router as defects_router
from app.routers.dashboard import router as dashboard_router
from app.routers.factories import router as factories_router
from app.routers.inspections import router as inspections_router
from app.routers.products import router as products_router
from app.routers.reports import router as reports_router
from app.routers.users import router as users_router
from app.core.rbac import rbac_template_context

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description=settings.app_description,
    version=settings.app_version,
    debug=settings.debug,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(auth_router)
app.include_router(factories_router)
app.include_router(products_router)
app.include_router(batches_router)
app.include_router(inspections_router)
app.include_router(defects_router)
app.include_router(dashboard_router)
app.include_router(reports_router)
app.include_router(users_router)
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update(rbac_template_context())


@app.get("/", response_class=HTMLResponse, tags=["Pages"])
def home(request: Request, current_user: Annotated[object | None, Depends(get_optional_current_user)] = None) -> HTMLResponse:
    """Render the public home page."""

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": current_user,
        },
    )


@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    """Return a simple health status for uptime checks."""

    return {"status": "ok", "service": settings.app_name}


@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    """Render browser-friendly authorization failures while preserving API errors."""

    if exc.status_code == status.HTTP_403_FORBIDDEN and "text/html" in request.headers.get("accept", ""):
        current_user = None
        try:
            db = next(get_db())
            current_user = get_optional_current_user(request, db)
        except Exception:
            current_user = None
        return templates.TemplateResponse(
            "not_authorized.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "app_description": settings.app_description,
                "current_user": current_user,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/not-authorized", response_class=HTMLResponse, include_in_schema=False)
def not_authorized_page(request: Request, current_user: Annotated[object | None, Depends(get_optional_current_user)] = None) -> HTMLResponse:
    """Render a direct not-authorized page."""

    return templates.TemplateResponse(
        "not_authorized.html",
        {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user},
        status_code=status.HTTP_403_FORBIDDEN,
    )
