"""Batch management routes."""

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
from app.models.factory import Batch, Inspection, Product, ProductionLine
from app.models.user import User
from app.routers.auth import ADMIN, QUALITY_MANAGER, get_current_user, get_optional_current_user, redirect_if_forbidden, require_role
from app.schemas.factory import BatchCreate, BatchList, BatchRead, BatchUpdate

router = APIRouter(prefix="/batches", tags=["Batches"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _pagination(page: int, per_page: int, page_size: int | None = None) -> tuple[int, int]:
    effective_size = page_size if page_size is not None else per_page
    return max(page, 1), min(max(effective_size, 1), 50)


def _normalize_status(value: str | None) -> str:
    status_value = (value or "planned").strip().lower()
    if status_value not in {"planned", "in_progress", "completed", "expired", "inactive"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid batch status")
    return status_value


def _parse_date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {field}") from exc


async def _batch_payload(request: Request, partial: bool = False) -> dict[str, object]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_payload = await request.json()
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid batch data")
        payload: dict[str, object] = {key: value for key, value in raw_payload.items() if value is not None}
    else:
        form_data = parse_qs((await request.body()).decode("utf-8"))
        payload = {key: values[0].strip() for key, values in form_data.items() if values}
    required = {"product_id", "production_line_id", "batch_number", "manufacturing_date", "expiry_date", "quantity"}
    if not partial and not required.issubset(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing batch data")
    for field in {"product_id", "production_line_id", "quantity"}.intersection(payload):
        try:
            payload[field] = int(str(payload[field]))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid batch data") from exc
    for field in {"batch_number"}.intersection(payload):
        payload[field] = str(payload[field]).strip()
        if not payload[field]:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid batch data")
    for field in {"manufacturing_date", "expiry_date"}.intersection(payload):
        payload[field] = _parse_date(payload[field], field)
    if "status" in payload or not partial:
        payload["status"] = _normalize_status(str(payload.get("status") or "planned"))
    return payload


def _get_batch_or_404(db: Session, batch_id: int) -> Batch:
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return batch


def _ensure_product(db: Session, product_id: int) -> None:
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")


def _ensure_production_line(db: Session, production_line_id: int) -> None:
    if db.get(ProductionLine, production_line_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Production line not found")


def _ensure_unique_batch_number(db: Session, batch_number: str, batch_id: int | None = None) -> None:
    query = select(Batch).where(Batch.batch_number == batch_number)
    if batch_id is not None:
        query = query.where(Batch.id != batch_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch number already exists")


def _validate_dates(manufacturing_date: date, expiry_date: date) -> None:
    if expiry_date <= manufacturing_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Expiry date must be after manufacturing date")


def _form_options(db: Session) -> dict[str, list]:
    return {"products": list(db.scalars(select(Product).where(Product.status == "active").order_by(Product.name)).all()), "production_lines": list(db.scalars(select(ProductionLine).where(ProductionLine.status == "active").order_by(ProductionLine.name)).all())}


@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
def new_batch_page(request: Request, db: Annotated[Session, Depends(get_db)], product_id: int | None = None) -> Response:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
    return templates.TemplateResponse("batches/form.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "batch": None, "selected_product_id": product_id, "form_action": "/batches", "form_title": "New Batch", **_form_options(db)})


@router.post("", response_model=BatchRead, status_code=status.HTTP_201_CREATED)
async def create_batch(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN))]) -> Batch | RedirectResponse:
    batch_data = BatchCreate(**await _batch_payload(request))
    _ensure_product(db, batch_data.product_id)
    _ensure_production_line(db, batch_data.production_line_id)
    _ensure_unique_batch_number(db, batch_data.batch_number)
    _validate_dates(batch_data.manufacturing_date, batch_data.expiry_date)
    batch = Batch(**batch_data.model_dump())
    db.add(batch); db.commit(); db.refresh(batch)
    if _wants_html(request):
        return RedirectResponse(url=f"/products/{batch.product_id}", status_code=status.HTTP_303_SEE_OTHER)
    return batch


@router.get("", response_model=BatchList)
def list_batches(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))], search: str | None = None, product_id: int | None = None, production_line_id: int | None = None, status_filter: str | None = None, start_date: date | None = None, end_date: date | None = None, sort_by: str = "manufacturing_date", sort_order: str = "desc", page: int = 1, page_size: int | None = None, per_page: int = 10) -> BatchList | HTMLResponse:
    page, per_page = _pagination(page, per_page, page_size)
    query = select(Batch)
    if search:
        term = f"%{search.strip()}%"
        query = query.join(Product).where(or_(Batch.batch_number.ilike(term), Product.name.ilike(term), Product.sku_code.ilike(term)))
    if product_id is not None:
        query = query.where(Batch.product_id == product_id)
    if production_line_id is not None:
        query = query.where(Batch.production_line_id == production_line_id)
    if status_filter:
        query = query.where(Batch.status == _normalize_status(status_filter))
    if start_date is not None:
        query = query.where(Batch.manufacturing_date >= start_date)
    if end_date is not None:
        query = query.where(Batch.manufacturing_date <= end_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(ceil(total / per_page), 1)
    sort_columns = {"id": Batch.id, "batch_number": Batch.batch_number, "manufacturing_date": Batch.manufacturing_date, "expiry_date": Batch.expiry_date, "quantity": Batch.quantity, "status": Batch.status, "created_at": Batch.created_at}
    sort_column = sort_columns.get(sort_by, Batch.manufacturing_date)
    direction = sort_order.lower()
    order_by = sort_column.asc() if direction == "asc" else sort_column.desc()
    batches = list(db.scalars(query.order_by(order_by, Batch.id.desc()).offset((page - 1) * per_page).limit(per_page)).all())
    if _wants_html(request):
        return templates.TemplateResponse("batches/list.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "batches": batches, "search": search or "", "product_id": product_id or "", "production_line_id": production_line_id or "", "status_filter": status_filter or "", "start_date": start_date or "", "end_date": end_date or "", "page": page, "per_page": per_page, "total": total, "pages": pages, "sort_by": sort_by, "sort_order": direction, "page_size": per_page, **_form_options(db)})
    return BatchList(items=batches, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/{batch_id}", response_model=BatchRead)
def get_batch(batch_id: int, request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> Batch | HTMLResponse:
    batch = _get_batch_or_404(db, batch_id)
    if _wants_html(request):
        inspections = list(db.scalars(select(Inspection).where(Inspection.batch_id == batch.id).order_by(Inspection.inspection_date.desc(), Inspection.id.desc())).all())
        return templates.TemplateResponse("batches/detail.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "batch": batch, "inspections": inspections})
    return batch


@router.get("/{batch_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_batch_page(batch_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
    batch = _get_batch_or_404(db, batch_id)
    return templates.TemplateResponse("batches/form.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "batch": batch, "selected_product_id": batch.product_id, "form_action": f"/batches/{batch.id}/edit", "form_title": "Edit Batch", **_form_options(db)})


@router.put("/{batch_id}", response_model=BatchRead)
async def update_batch(batch_id: int, request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN))]) -> Batch:
    batch = _get_batch_or_404(db, batch_id)
    updates = BatchUpdate(**await _batch_payload(request, partial=True)).model_dump(exclude_unset=True)
    if "product_id" in updates:
        _ensure_product(db, updates["product_id"])
    if "production_line_id" in updates:
        _ensure_production_line(db, updates["production_line_id"])
    if "batch_number" in updates:
        _ensure_unique_batch_number(db, updates["batch_number"], batch.id)
    manufacturing_date = updates.get("manufacturing_date", batch.manufacturing_date)
    expiry_date = updates.get("expiry_date", batch.expiry_date)
    _validate_dates(manufacturing_date, expiry_date)
    for field, value in updates.items():
        setattr(batch, field, value)
    db.commit(); db.refresh(batch)
    return batch


@router.post("/{batch_id}/edit", include_in_schema=False)
async def update_batch_from_form(batch_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    batch = await update_batch(batch_id, request, db, current_user)
    return RedirectResponse(url=f"/products/{batch.product_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/{batch_id}", response_model=BatchRead)
def delete_batch(batch_id: int, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN))]) -> Batch:
    batch = _get_batch_or_404(db, batch_id)
    batch.status = "inactive"
    db.commit(); db.refresh(batch)
    return batch


@router.post("/{batch_id}/delete", include_in_schema=False)
def delete_batch_from_form(batch_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
    batch = _get_batch_or_404(db, batch_id)
    batch.status = "inactive"
    db.commit()
    return RedirectResponse(url=f"/products/{batch.product_id}", status_code=status.HTTP_303_SEE_OTHER)
