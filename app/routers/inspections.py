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
from app.routers.auth import get_current_user, get_optional_current_user
from app.schemas.factory import InspectionCreate, InspectionList, InspectionRead, InspectionUpdate

router = APIRouter(tags=["Inspections"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
CHECK_FIELDS = ("scratch", "color", "packaging", "functional_test")


def _wants_html(request: Request) -> bool:
    """Return whether a request prefers an HTML response."""

    return "text/html" in request.headers.get("accept", "")


def _pagination(page: int, per_page: int) -> tuple[int, int]:
    """Normalize pagination inputs."""

    return max(page, 1), min(max(per_page, 1), 50)


def _normalize_check(value: object, field: str) -> str:
    """Normalize a pass/fail inspection check value."""

    check_value = str(value).strip().lower()
    if check_value not in {"pass", "fail"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {field} result")
    return check_value


def _normalize_overall_status(value: object | None) -> str | None:
    """Normalize an optional overall inspection status."""

    if value is None or str(value).strip() == "":
        return None
    status_value = str(value).strip().lower()
    if status_value not in {"pass", "fail"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid overall status")
    return "Pass" if status_value == "pass" else "Fail"


def _calculate_overall_status(payload: dict[str, object]) -> str:
    """Calculate overall status from individual pass/fail checks."""

    return "Fail" if any(payload[field] == "fail" for field in CHECK_FIELDS) else "Pass"


def _calculate_score(payload: dict[str, object]) -> float:
    """Calculate a simple percentage score from individual pass/fail checks."""

    passed = sum(1 for field in CHECK_FIELDS if payload[field] == "pass")
    return round((passed / len(CHECK_FIELDS)) * 100, 2)


def _apply_overall_status(payload: dict[str, object]) -> dict[str, object]:
    """Set calculated or justified override overall status and score."""

    calculated = _calculate_overall_status(payload)
    requested = _normalize_overall_status(payload.get("overall_status"))
    remarks = str(payload.get("remarks") or "").strip()
    if requested is not None and requested != calculated and not remarks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Remarks are required to override calculated overall status",
        )
    payload["overall_status"] = requested or calculated
    payload["inspection_score"] = _calculate_score(payload)
    payload["remarks"] = remarks
    return payload


def _parse_float(value: object, field: str) -> float:
    """Parse a positive decimal inspection value."""

    try:
        parsed = float(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {field}") from exc
    if parsed < 0 or (field == "weight_spec" and parsed <= 0):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {field}")
    return parsed


async def _inspection_payload(request: Request, partial: bool = False) -> dict[str, object]:
    """Read JSON or URL-encoded inspection fields from a request."""

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_payload = await request.json()
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid inspection data")
        payload: dict[str, object] = {key: value for key, value in raw_payload.items() if value is not None}
    else:
        form_data = parse_qs((await request.body()).decode("utf-8"))
        payload = {key: values[0].strip() for key, values in form_data.items() if values}

    required = {
        "batch_id",
        "scratch",
        "color",
        "weight_actual",
        "weight_spec",
        "dimensions_actual",
        "dimensions_spec",
        "packaging",
        "functional_test",
    }
    if not partial and not required.issubset(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing inspection data")

    if "batch_id" in payload:
        try:
            payload["batch_id"] = int(str(payload["batch_id"]))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid batch") from exc
    for field in CHECK_FIELDS:
        if field in payload:
            payload[field] = _normalize_check(payload[field], field)
    for field in {"weight_actual", "weight_spec"}.intersection(payload):
        payload[field] = _parse_float(payload[field], field)
    for field in {"dimensions_actual", "dimensions_spec"}.intersection(payload):
        payload[field] = str(payload[field]).strip()
        if not payload[field]:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid dimensions")
    if "overall_status" in payload:
        payload["overall_status"] = _normalize_overall_status(payload.get("overall_status"))
    if "remarks" in payload:
        payload["remarks"] = str(payload["remarks"]).strip()
    return payload


def _get_batch_or_404(db: Session, batch_id: int) -> Batch:
    """Return a batch by id or raise 404."""

    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return batch


def _get_inspection_or_404(db: Session, inspection_id: int) -> Inspection:
    """Return an inspection by id or raise 404."""

    inspection = db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found")
    return inspection


def _form_options(db: Session) -> dict[str, list[Batch]]:
    """Return option lists for inspection forms."""

    return {"batches": list(db.scalars(select(Batch).order_by(Batch.batch_number)).all())}


def _inspection_query(
    search: str | None = None,
    product_id: int | None = None,
    batch_id: int | None = None,
    inspector_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Build an inspection filter query."""

    query = select(Inspection)
    joined_product = False
    if search:
        term = f"%{search.strip()}%"
        query = query.join(Batch).join(Product).where(
            or_(Batch.batch_number.ilike(term), Product.name.ilike(term), Product.sku_code.ilike(term))
        )
        joined_product = True
    if product_id is not None:
        if not joined_product:
            query = query.join(Batch)
        query = query.where(Batch.product_id == product_id)
    if batch_id is not None:
        query = query.where(Inspection.batch_id == batch_id)
    if inspector_id is not None:
        query = query.where(Inspection.inspector_id == inspector_id)
    if status_filter:
        query = query.where(Inspection.overall_status == _normalize_overall_status(status_filter))
    if start_date is not None:
        query = query.where(func.date(Inspection.inspection_date) >= start_date.isoformat())
    if end_date is not None:
        query = query.where(func.date(Inspection.inspection_date) <= end_date.isoformat())
    return query


def _list_response(
    request: Request,
    db: Session,
    current_user: User,
    search: str | None,
    product_id: int | None,
    batch_id: int | None,
    inspector_id: int | None,
    status_filter: str | None,
    start_date: date | None,
    end_date: date | None,
    page: int,
    per_page: int,
) -> InspectionList | HTMLResponse:
    """Return a paginated inspection response in JSON or HTML."""

    page, per_page = _pagination(page, per_page)
    query = _inspection_query(search, product_id, batch_id, inspector_id, status_filter, start_date, end_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(ceil(total / per_page), 1)
    inspections = list(
        db.scalars(query.order_by(Inspection.inspection_date.desc(), Inspection.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    )
    if _wants_html(request):
        products = list(db.scalars(select(Product).order_by(Product.name)).all())
        batches = list(db.scalars(select(Batch).order_by(Batch.batch_number)).all())
        inspectors = list(db.scalars(select(User).order_by(User.username)).all())
        return templates.TemplateResponse(
            "inspections/list.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "app_description": settings.app_description,
                "current_user": current_user,
                "inspections": inspections,
                "products": products,
                "batches": batches,
                "inspectors": inspectors,
                "search": search or "",
                "product_id": product_id or "",
                "batch_id": batch_id or "",
                "inspector_id": inspector_id or "",
                "status_filter": status_filter or "",
                "start_date": start_date or "",
                "end_date": end_date or "",
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": pages,
            },
        )
    return InspectionList(items=inspections, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/inspections/new", response_class=HTMLResponse, include_in_schema=False)
def new_inspection_page(request: Request, db: Annotated[Session, Depends(get_db)], batch_id: int | None = None) -> Response:
    """Render the inspection creation form."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "inspections/form.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": current_user,
            "inspection": None,
            "selected_batch_id": batch_id,
            "form_action": "/inspections",
            "form_title": "New Inspection",
            **_form_options(db),
        },
    )


@router.post("/inspections", response_model=InspectionRead, status_code=status.HTTP_201_CREATED)
async def create_inspection(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Inspection | RedirectResponse:
    """Create an inspection attributed to the current user."""

    payload = InspectionCreate(**await _inspection_payload(request)).model_dump()
    _get_batch_or_404(db, payload["batch_id"])
    payload = _apply_overall_status(payload)
    inspection = Inspection(inspector_id=current_user.id, **payload)
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    if _wants_html(request):
        return RedirectResponse(url=f"/batches/{inspection.batch_id}", status_code=status.HTTP_303_SEE_OTHER)
    return inspection


@router.get("/inspections", response_model=InspectionList)
def list_inspections(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    search: str | None = None,
    product_id: int | None = None,
    batch_id: int | None = None,
    inspector_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = 10,
) -> InspectionList | HTMLResponse:
    """List inspections with search, filters, and pagination."""

    return _list_response(request, db, current_user, search, product_id, batch_id, inspector_id, status_filter, start_date, end_date, page, per_page)


@router.get("/inspections/search", response_model=InspectionList)
def search_inspections(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    q: str | None = None,
    page: int = 1,
    per_page: int = 10,
) -> InspectionList | HTMLResponse:
    """Search inspections by batch number, product name, or SKU."""

    return _list_response(request, db, current_user, q, None, None, None, None, None, None, page, per_page)


@router.get("/inspections/filter", response_model=InspectionList)
def filter_inspections(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    product_id: int | None = None,
    batch_id: int | None = None,
    inspector_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = 10,
) -> InspectionList | HTMLResponse:
    """Filter inspections by product, batch, inspector, status, and date range."""

    return _list_response(request, db, current_user, None, product_id, batch_id, inspector_id, status_filter, start_date, end_date, page, per_page)


@router.get("/inspections/{inspection_id}", response_model=InspectionRead)
def get_inspection(
    inspection_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Inspection:
    """Return one inspection."""

    return _get_inspection_or_404(db, inspection_id)


@router.get("/inspections/{inspection_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_inspection_page(inspection_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Render the inspection edit form."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    inspection = _get_inspection_or_404(db, inspection_id)
    return templates.TemplateResponse(
        "inspections/form.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": current_user,
            "inspection": inspection,
            "selected_batch_id": inspection.batch_id,
            "form_action": f"/inspections/{inspection.id}/edit",
            "form_title": "Edit Inspection",
            **_form_options(db),
        },
    )


@router.put("/inspections/{inspection_id}", response_model=InspectionRead)
async def update_inspection(
    inspection_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Inspection:
    """Update an inspection without changing the original inspector."""

    inspection = _get_inspection_or_404(db, inspection_id)
    updates = InspectionUpdate(**await _inspection_payload(request, partial=True)).model_dump(exclude_unset=True)
    if "batch_id" in updates:
        _get_batch_or_404(db, updates["batch_id"])
    merged = {
        "batch_id": inspection.batch_id,
        "scratch": inspection.scratch,
        "color": inspection.color,
        "weight_actual": inspection.weight_actual,
        "weight_spec": inspection.weight_spec,
        "dimensions_actual": inspection.dimensions_actual,
        "dimensions_spec": inspection.dimensions_spec,
        "packaging": inspection.packaging,
        "functional_test": inspection.functional_test,
        "overall_status": inspection.overall_status,
        "remarks": inspection.remarks,
    }
    merged.update(updates)
    if "overall_status" not in updates:
        merged["overall_status"] = None
    merged = _apply_overall_status(merged)
    for field, value in merged.items():
        if field in {"overall_status", "inspection_score"} or field in updates:
            setattr(inspection, field, value)
    db.commit()
    db.refresh(inspection)
    return inspection


@router.post("/inspections/{inspection_id}/edit", include_in_schema=False)
async def update_inspection_from_form(inspection_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    """Update an inspection from the HTML form."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    inspection = await update_inspection(inspection_id, request, db, current_user)
    return RedirectResponse(url=f"/batches/{inspection.batch_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/inspections/{inspection_id}", response_model=InspectionRead)
def delete_inspection(
    inspection_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Inspection:
    """Delete an inspection record."""

    inspection = _get_inspection_or_404(db, inspection_id)
    db.delete(inspection)
    db.commit()
    return inspection


@router.post("/inspections/{inspection_id}/delete", include_in_schema=False)
def delete_inspection_from_form(inspection_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    """Delete an inspection from the HTML batch detail page."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    inspection = _get_inspection_or_404(db, inspection_id)
    batch_id = inspection.batch_id
    db.delete(inspection)
    db.commit()
    return RedirectResponse(url=f"/batches/{batch_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/batches/{batch_id}/inspections", response_model=InspectionList)
def batch_inspection_history(
    batch_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    page: int = 1,
    per_page: int = 10,
) -> InspectionList:
    """Return inspection history for one batch."""

    _get_batch_or_404(db, batch_id)
    page, per_page = _pagination(page, per_page)
    query = select(Inspection).where(Inspection.batch_id == batch_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(ceil(total / per_page), 1)
    inspections = list(db.scalars(query.order_by(Inspection.inspection_date.desc(), Inspection.id.desc()).offset((page - 1) * per_page).limit(per_page)).all())
    return InspectionList(items=inspections, page=page, per_page=per_page, total=total, pages=pages)
