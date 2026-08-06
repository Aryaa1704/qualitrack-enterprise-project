"""FastAPI application entry point for QualiTrack."""

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.database.session import get_db
from app.models.factory import Batch, Defect, Inspection, Product
from app.models.user import User
from app.routers.auth import get_current_user, get_optional_current_user, router as auth_router
from app.routers.batches import router as batches_router
from app.routers.defects import router as defects_router
from app.routers.dashboard import router as dashboard_router
from app.routers.factories import router as factories_router
from app.routers.inspections import router as inspections_router
from app.routers.products import router as products_router
from app.routers.reports import router as reports_router

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
templates = Jinja2Templates(directory="app/templates")


@app.get("/search", tags=["Search"], response_model=None)
def global_search(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)], q: str = "") -> dict[str, list[dict[str, object]]] | HTMLResponse:
    """Search products, batches, inspections, and defects by keyword and group the results."""

    term = q.strip()
    like_term = f"%{term}%"
    products = []
    batches = []
    inspections = []
    defects = []
    if term:
        products = list(db.scalars(select(Product).where(or_(Product.name.ilike(like_term), Product.sku_code.ilike(like_term), Product.category.ilike(like_term))).order_by(Product.name).limit(10)).all())
        batches = list(db.scalars(select(Batch).join(Product).where(or_(Batch.batch_number.ilike(like_term), Product.name.ilike(like_term), Product.sku_code.ilike(like_term))).order_by(Batch.manufacturing_date.desc(), Batch.id.desc()).limit(10)).all())
        inspections = list(db.scalars(select(Inspection).join(Batch).join(Product).join(User, Inspection.inspector_id == User.id).where(or_(Batch.batch_number.ilike(like_term), Product.name.ilike(like_term), Product.sku_code.ilike(like_term), User.username.ilike(like_term), Inspection.overall_status.ilike(like_term), Inspection.remarks.ilike(like_term))).order_by(Inspection.inspection_date.desc(), Inspection.id.desc()).limit(10)).all())
        defects = list(db.scalars(select(Defect).join(Inspection).where(or_(Defect.defect_type.ilike(like_term), Defect.severity.ilike(like_term), Defect.status.ilike(like_term), Defect.description.ilike(like_term), Defect.corrective_action.ilike(like_term))).order_by(Defect.created_at.desc(), Defect.id.desc()).limit(10)).all())
    if "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse("search.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "q": term, "products": products, "batches": batches, "inspections": inspections, "defects": defects})
    return {
        "products": [{"id": item.id, "label": item.name, "sku_code": item.sku_code, "url": f"/products/{item.id}"} for item in products],
        "batches": [{"id": item.id, "label": item.batch_number, "product": item.product.name, "url": f"/batches/{item.id}"} for item in batches],
        "inspections": [{"id": item.id, "label": f"Inspection #{item.id}", "status": item.overall_status, "url": f"/inspections/{item.id}"} for item in inspections],
        "defects": [{"id": item.id, "label": item.defect_type, "severity": item.severity, "status": item.status, "url": f"/defects/{item.id}/edit"} for item in defects],
    }


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
