"""FastAPI application entry point for QualiTrack."""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.routers.activity_logs import router as activity_logs_router
from app.routers.auth import ADMIN, INSPECTOR, QUALITY_MANAGER, get_optional_current_user, require_role, router as auth_router
from app.routers.batches import router as batches_router
from app.routers.defects import router as defects_router
from app.routers.dashboard import router as dashboard_router
from app.routers.factories import router as factories_router
from app.routers.inspections import router as inspections_router
from app.routers.products import router as products_router
from app.routers.reports import router as reports_router
from app.models.factory import Batch, Defect, Inspection, Product

settings = get_settings()
from app.database.session import engine
from app.database.base import Base
app = FastAPI(
    title=settings.app_name,
    description=settings.app_description,
    version=settings.app_version,
    debug=settings.debug,
)

@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(auth_router)
app.include_router(factories_router)
app.include_router(products_router)
app.include_router(batches_router)
app.include_router(inspections_router)
app.include_router(defects_router)
app.include_router(dashboard_router)
app.include_router(reports_router)
app.include_router(activity_logs_router)
templates = Jinja2Templates(directory="app/templates")


def _error_code(status_code: int) -> str:
    """Return a stable machine-readable error code for an HTTP status."""

    return {
        status.HTTP_400_BAD_REQUEST: "bad_request",
        status.HTTP_401_UNAUTHORIZED: "not_authenticated",
        status.HTTP_403_FORBIDDEN: "not_authorized",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_422_UNPROCESSABLE_ENTITY: "validation_error",
    }.get(status_code, "http_error")


def _error_response(status_code: int, detail: object, code: str | None = None) -> JSONResponse:
    """Build the standard API error response shape used by every router."""

    return JSONResponse(status_code=status_code, content={"detail": detail, "code": code or _error_code(status_code)})


@app.exception_handler(HTTPException)
async def html_forbidden_redirect(request: Request, exc: HTTPException):
    """Redirect browser users to a not-authorized page while preserving standardized API errors."""

    if exc.status_code == status.HTTP_403_FORBIDDEN and "text/html" in request.headers.get("accept", "") and request.url.path != "/auth/not-authorized":
        return RedirectResponse(url="/auth/not-authorized", status_code=status.HTTP_303_SEE_OTHER)
    return _error_response(exc.status_code, exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return FastAPI/Pydantic validation errors in the standard API error envelope."""

    return _error_response(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errors(), "validation_error")


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


@app.get("/search", tags=["Search"], response_model=None)
def global_search(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[object, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))], q: str = "") -> dict[str, list[dict[str, object]]] | HTMLResponse:
    """Search products, batches, inspections, and defects and return grouped results."""

    if current_user is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    term_value = q.strip()
    wildcard = f"%{term_value}%"
    groups: dict[str, list[dict[str, object]]] = {"products": [], "batches": [], "inspections": [], "defects": []}
    if term_value:
        products = db.scalars(select(Product).where(or_(Product.name.ilike(wildcard), Product.sku_code.ilike(wildcard), Product.category.ilike(wildcard))).order_by(Product.name).limit(10)).all()
        groups["products"] = [{"id": item.id, "label": item.name, "description": item.sku_code, "url": f"/products/{item.id}"} for item in products]
        batches = db.scalars(select(Batch).join(Product).where(or_(Batch.batch_number.ilike(wildcard), Product.name.ilike(wildcard), Product.sku_code.ilike(wildcard))).order_by(Batch.manufacturing_date.desc(), Batch.id.desc()).limit(10)).all()
        groups["batches"] = [{"id": item.id, "label": item.batch_number, "description": item.product.name, "url": f"/batches/{item.id}"} for item in batches]
        inspections = db.scalars(select(Inspection).join(Batch).join(Product).where(or_(Batch.batch_number.ilike(wildcard), Product.name.ilike(wildcard), Product.sku_code.ilike(wildcard), Inspection.overall_status.ilike(wildcard), Inspection.remarks.ilike(wildcard))).order_by(Inspection.inspection_date.desc(), Inspection.id.desc()).limit(10)).all()
        groups["inspections"] = [{"id": item.id, "label": f"Inspection #{item.id}", "description": f"{item.batch.batch_number} · {item.overall_status}", "url": f"/inspections/{item.id}"} for item in inspections]
        defects = db.scalars(select(Defect).where(or_(Defect.defect_type.ilike(wildcard), Defect.severity.ilike(wildcard), Defect.description.ilike(wildcard), Defect.corrective_action.ilike(wildcard), Defect.status.ilike(wildcard))).order_by(Defect.created_at.desc(), Defect.id.desc()).limit(10)).all()
        groups["defects"] = [{"id": item.id, "label": item.defect_type, "description": f"{item.severity} · {item.status}", "url": f"/defects/{item.id}/edit"} for item in defects]
    if "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse("search.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "q": term_value, "groups": groups})
    return groups


@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    """Return a simple health status for uptime checks."""

    return {"status": "ok", "service": settings.app_name}
