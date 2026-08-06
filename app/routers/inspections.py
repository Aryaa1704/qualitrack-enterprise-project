"""Quality inspection workflow routes."""

from datetime import date
from math import ceil
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.models.factory import Batch, Inspection, Product
from app.models.user import User
from app.routers.auth import ADMIN, INSPECTOR, QUALITY_MANAGER, get_current_user, get_optional_current_user, redirect_if_forbidden, require_role
from app.schemas.factory import InspectionCreate, InspectionList, InspectionRead, InspectionUpdate
from app.services.activity import INSPECTION_CREATED, INSPECTION_UPDATED, log_activity

router = APIRouter(prefix="/inspections", tags=["Inspections"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
CHECK_FIELDS = ("scratch", "color", "packaging", "functional_test")


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _pagination(page: int, per_page: int, page_size: int | None = None) -> tuple[int, int]:
    effective_size = page_size if page_size is not None else per_page
    return max(page, 1), min(max(effective_size, 1), 50)


def _normalize_check(value: object) -> str:
    check = str(value).strip().lower()
    if check not in {"pass", "fail"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Inspection checks must be pass or fail")
    return check


def _calculated_status(payload: dict[str, object]) -> str:
    return "Fail" if any(payload[field] == "fail" for field in CHECK_FIELDS) else "Pass"


def _final_status(payload: dict[str, object], existing: Inspection | None = None) -> str:
    values = {field: payload.get(field, getattr(existing, field) if existing else None) for field in CHECK_FIELDS}
    calculated = _calculated_status(values)
    requested = payload.get("overall_status")
    if not requested:
        return calculated
    requested_status = str(requested).strip().title()
    if requested_status not in {"Pass", "Fail"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid overall status")
    remarks = str(payload.get("remarks", getattr(existing, "remarks", "") if existing else "")).strip()
    if requested_status != calculated and not remarks:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Remarks are required to override calculated status")
    return requested_status


async def _inspection_payload(request: Request, partial: bool = False) -> dict[str, object]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_payload = await request.json()
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid inspection data")
        payload: dict[str, object] = {key: value for key, value in raw_payload.items() if value is not None}
    else:
        form_data = parse_qs((await request.body()).decode("utf-8"))
        payload = {key: values[0].strip() for key, values in form_data.items() if values}
    payload.pop("inspector_id", None)
    required = {"batch_id", "scratch", "color", "weight_actual", "weight_spec", "dimensions_actual", "dimensions_spec", "packaging", "functional_test", "inspection_score"}
    if not partial and not required.issubset(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing inspection data")
    for field in {"batch_id", "inspection_score"}.intersection(payload):
        try:
            payload[field] = int(str(payload[field]))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid inspection data") from exc
    for field in {"weight_actual", "weight_spec"}.intersection(payload):
        try:
            payload[field] = float(str(payload[field]))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid inspection data") from exc
    for field in set(CHECK_FIELDS).intersection(payload):
        payload[field] = _normalize_check(payload[field])
    for field in {"dimensions_actual", "dimensions_spec"}.intersection(payload):
        payload[field] = str(payload[field]).strip()
        if not payload[field]:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid inspection dimensions")
    if "remarks" in payload:
        payload["remarks"] = str(payload["remarks"]).strip()
    return payload


def _get_inspection_or_404(db: Session, inspection_id: int) -> Inspection:
    inspection = db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found")
    return inspection


def _ensure_batch(db: Session, batch_id: int) -> None:
    if db.get(Batch, batch_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")


def _form_options(db: Session) -> dict[str, list[Batch]]:
    return {"batches": list(db.scalars(select(Batch).order_by(Batch.batch_number)).all())}


def _inspection_query(search: str | None, product_id: int | None, batch_id: int | None, inspector_id: int | None, status_filter: str | None, start_date: date | None, end_date: date | None):
    query = select(Inspection).join(Batch).join(Product)
    if search:
        term = f"%{search.strip()}%"
        query = query.join(User, Inspection.inspector_id == User.id).where(or_(Batch.batch_number.ilike(term), Product.name.ilike(term), Product.sku_code.ilike(term), User.username.ilike(term)))
    if product_id is not None:
        query = query.where(Batch.product_id == product_id)
    if batch_id is not None:
        query = query.where(Inspection.batch_id == batch_id)
    if inspector_id is not None:
        query = query.where(Inspection.inspector_id == inspector_id)
    if status_filter:
        query = query.where(Inspection.overall_status == status_filter.strip().title())
    if start_date is not None:
        query = query.where(func.date(Inspection.inspection_date) >= start_date.isoformat())
    if end_date is not None:
        query = query.where(func.date(Inspection.inspection_date) <= end_date.isoformat())
    return query


@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
def new_inspection_page(request: Request, db: Annotated[Session, Depends(get_db)], batch_id: int | None = None) -> Response:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("inspections/form.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "inspection": None, "selected_batch_id": batch_id, "form_action": "/inspections", "form_title": "New Inspection", **_form_options(db)})


@router.post("", response_model=InspectionRead, status_code=status.HTTP_201_CREATED)
async def create_inspection(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> Inspection | RedirectResponse:
    payload = await _inspection_payload(request)
    payload["overall_status"] = _final_status(payload)
    inspection_data = InspectionCreate(**payload)
    _ensure_batch(db, inspection_data.batch_id)
    inspection = Inspection(**inspection_data.model_dump(), inspector_id=current_user.id)
    db.add(inspection); db.flush()
    log_activity(db, current_user, INSPECTION_CREATED, "inspection", inspection.id, f"Created inspection #{inspection.id} for batch {inspection.batch.batch_number}", commit=False)
    db.commit(); db.refresh(inspection)
    if _wants_html(request):
        return RedirectResponse(url=f"/batches/{inspection.batch_id}", status_code=status.HTTP_303_SEE_OTHER)
    return inspection


@router.get("", response_model=InspectionList)
def list_inspections(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))], search: str | None = None, product_id: int | None = None, batch_id: int | None = None, inspector_id: int | None = None, status_filter: str | None = None, start_date: date | None = None, end_date: date | None = None, sort_by: str = "inspection_date", sort_order: str = "desc", page: int = 1, page_size: int | None = None, per_page: int = 10) -> InspectionList | HTMLResponse:
    page, per_page = _pagination(page, per_page, page_size)
    query = _inspection_query(search, product_id, batch_id, inspector_id, status_filter, start_date, end_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(ceil(total / per_page), 1)
    sort_columns = {"id": Inspection.id, "inspection_date": Inspection.inspection_date, "overall_status": Inspection.overall_status, "inspection_score": Inspection.inspection_score, "batch_id": Inspection.batch_id, "inspector_id": Inspection.inspector_id}
    sort_column = sort_columns.get(sort_by, Inspection.inspection_date)
    direction = sort_order.lower()
    order_by = sort_column.asc() if direction == "asc" else sort_column.desc()
    inspections = list(db.scalars(query.order_by(order_by, Inspection.id.desc()).offset((page - 1) * per_page).limit(per_page)).all())
    if _wants_html(request):
        return templates.TemplateResponse("inspections/list.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "inspections": inspections, "search": search or "", "product_id": product_id or "", "batch_id": batch_id or "", "inspector_id": inspector_id or "", "status_filter": status_filter or "", "start_date": start_date or "", "end_date": end_date or "", "page": page, "per_page": per_page, "total": total, "pages": pages, "sort_by": sort_by, "sort_order": direction, "page_size": per_page, **_form_options(db)})
    return InspectionList(items=inspections, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/search", response_model=InspectionList)
def search_inspections(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))], q: str | None = None, status_filter: str | None = None, sort_by: str = "inspection_date", sort_order: str = "desc", page: int = 1, page_size: int | None = None, per_page: int = 10) -> InspectionList | HTMLResponse:
    return list_inspections(request, db, current_user, search=q, status_filter=status_filter, sort_by=sort_by, sort_order=sort_order, page=page, page_size=page_size, per_page=per_page)


@router.get("/filter", response_model=InspectionList)
def filter_inspections(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))], product_id: int | None = None, batch_id: int | None = None, inspector_id: int | None = None, status_filter: str | None = None, start_date: date | None = None, end_date: date | None = None, sort_by: str = "inspection_date", sort_order: str = "desc", page: int = 1, page_size: int | None = None, per_page: int = 10) -> InspectionList | HTMLResponse:
    return list_inspections(request, db, current_user, product_id=product_id, batch_id=batch_id, inspector_id=inspector_id, status_filter=status_filter, start_date=start_date, end_date=end_date, sort_by=sort_by, sort_order=sort_order, page=page, page_size=page_size, per_page=per_page)


@router.get("/batch/{batch_id}/history", response_model=list[InspectionRead])
def batch_inspection_history(batch_id: int, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> list[Inspection]:
    _ensure_batch(db, batch_id)
    return list(db.scalars(select(Inspection).where(Inspection.batch_id == batch_id).order_by(Inspection.inspection_date.desc(), Inspection.id.desc())).all())


@router.get("/{inspection_id}", response_model=InspectionRead)
def get_inspection(inspection_id: int, request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> Inspection | HTMLResponse:
    inspection = _get_inspection_or_404(db, inspection_id)
    if _wants_html(request):
        return templates.TemplateResponse("inspections/detail.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "inspection": inspection})
    return inspection


@router.get("/{inspection_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_inspection_page(inspection_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    inspection = _get_inspection_or_404(db, inspection_id)
    return templates.TemplateResponse("inspections/form.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "inspection": inspection, "selected_batch_id": inspection.batch_id, "form_action": f"/inspections/{inspection.id}/edit", "form_title": "Edit Inspection", **_form_options(db)})


@router.put("/{inspection_id}", response_model=InspectionRead)
async def update_inspection(inspection_id: int, request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> Inspection:
    inspection = _get_inspection_or_404(db, inspection_id)
    payload = await _inspection_payload(request, partial=True)
    if "batch_id" in payload:
        _ensure_batch(db, int(payload["batch_id"]))
    payload["overall_status"] = _final_status(payload, inspection)
    updates = InspectionUpdate(**payload).model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(inspection, field, value)
    log_activity(db, current_user, INSPECTION_UPDATED, "inspection", inspection.id, f"Updated inspection #{inspection.id} for batch {inspection.batch.batch_number}", commit=False)
    db.commit(); db.refresh(inspection)
    return inspection


@router.post("/{inspection_id}/edit", include_in_schema=False)
async def update_inspection_from_form(inspection_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    inspection = await update_inspection(inspection_id, request, db, current_user)
    return RedirectResponse(url=f"/batches/{inspection.batch_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/{inspection_id}", response_model=InspectionRead)
def delete_inspection(inspection_id: int, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> Inspection:
    inspection = _get_inspection_or_404(db, inspection_id)
    db.delete(inspection); db.commit()
    return inspection


@router.post("/{inspection_id}/delete", include_in_schema=False)
def delete_inspection_from_form(inspection_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    inspection = _get_inspection_or_404(db, inspection_id)
    batch_id = inspection.batch_id
    db.delete(inspection); db.commit()
    return RedirectResponse(url=f"/batches/{batch_id}", status_code=status.HTTP_303_SEE_OTHER)
