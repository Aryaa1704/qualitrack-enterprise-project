"""Defect tracking routes."""

from datetime import date, datetime, timezone
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
from app.models.factory import Defect, Inspection
from app.models.user import User
from app.routers.auth import ADMIN, INSPECTOR, QUALITY_MANAGER, get_current_user, get_optional_current_user, redirect_if_forbidden, require_role
from app.schemas.factory import DefectCreate, DefectList, DefectRead, DefectStats, DefectUpdate
from app.services.activity import DEFECT_CREATED, DEFECT_UPDATED, log_activity

router = APIRouter(prefix="/defects", tags=["Defects"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
DEFECT_TYPES = ("Crack", "Scratch", "Missing Part", "Paint Issue", "Loose Component", "Wrong Label", "Custom")
SEVERITIES = ("Low", "Medium", "High")
DEFECT_STATUSES = ("Open", "In Progress", "Resolved")


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _pagination(page: int, per_page: int, page_size: int | None = None) -> tuple[int, int]:
    effective_size = page_size if page_size is not None else per_page
    return max(page, 1), min(max(effective_size, 1), 50)


def _normalize_choice(value: object, choices: tuple[str, ...], field: str) -> str:
    normalized = str(value).strip()
    if normalized not in choices:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {field}")
    return normalized


def _get_defect_or_404(db: Session, defect_id: int) -> Defect:
    defect = db.get(Defect, defect_id)
    if defect is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Defect not found")
    return defect


def _get_inspection_or_404(db: Session, inspection_id: int) -> Inspection:
    inspection = db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found")
    return inspection


def _ensure_failed_inspection(db: Session, inspection_id: int) -> Inspection:
    inspection = _get_inspection_or_404(db, inspection_id)
    if inspection.overall_status != "Fail":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Defects can only be linked to failed inspections")
    return inspection


async def _defect_payload(request: Request, partial: bool = False) -> dict[str, object]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_payload = await request.json()
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid defect data")
        payload: dict[str, object] = {key: value for key, value in raw_payload.items() if value is not None}
    else:
        form_data = parse_qs((await request.body()).decode("utf-8"))
        payload = {key: values[0].strip() for key, values in form_data.items() if values}
    required = {"inspection_id", "defect_type", "severity", "description"}
    if not partial and not required.issubset(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing defect data")
    if "inspection_id" in payload:
        try:
            payload["inspection_id"] = int(str(payload["inspection_id"]))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid inspection") from exc
    if "defect_type" in payload:
        payload["defect_type"] = _normalize_choice(payload["defect_type"], DEFECT_TYPES, "defect type")
    if "severity" in payload:
        payload["severity"] = _normalize_choice(payload["severity"], SEVERITIES, "severity")
    if "status" in payload:
        payload["status"] = _normalize_choice(payload["status"], DEFECT_STATUSES, "status")
    elif not partial:
        payload["status"] = "Open"
    for field in {"description", "corrective_action"}.intersection(payload):
        payload[field] = str(payload[field]).strip()
    if not partial and not payload.get("description"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Description is required")
    return payload


def _apply_resolution(defect: Defect, new_status: str) -> None:
    if new_status == "Resolved" and defect.resolved_date is None:
        defect.resolved_date = datetime.now(timezone.utc)
    elif new_status != "Resolved":
        defect.resolved_date = None


def _defect_query(search: str | None, defect_type: str | None, severity: str | None, status_filter: str | None, start_date: date | None, end_date: date | None):
    query = select(Defect)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Defect.defect_type.ilike(term), Defect.severity.ilike(term), Defect.description.ilike(term), Defect.corrective_action.ilike(term), Defect.status.ilike(term)))
    if defect_type:
        query = query.where(Defect.defect_type == _normalize_choice(defect_type, DEFECT_TYPES, "defect type"))
    if severity:
        query = query.where(Defect.severity == _normalize_choice(severity, SEVERITIES, "severity"))
    if status_filter:
        query = query.where(Defect.status == _normalize_choice(status_filter, DEFECT_STATUSES, "status"))
    if start_date is not None:
        query = query.where(func.date(Defect.created_at) >= start_date.isoformat())
    if end_date is not None:
        query = query.where(func.date(Defect.created_at) <= end_date.isoformat())
    return query


def _template_context(request: Request, current_user: User, **extra: object) -> dict[str, object]:
    return {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "defect_types": DEFECT_TYPES, "severities": SEVERITIES, "defect_statuses": DEFECT_STATUSES, **extra}


@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
def new_defect_page(request: Request, db: Annotated[Session, Depends(get_db)], inspection_id: int) -> Response:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    inspection = _ensure_failed_inspection(db, inspection_id)
    return templates.TemplateResponse("defects/form.html", _template_context(request, current_user, defect=None, inspection=inspection, form_action="/defects", form_title="Add Defect"))


@router.post("", response_model=DefectRead, status_code=status.HTTP_201_CREATED)
async def create_defect(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> Defect | RedirectResponse:
    defect_data = DefectCreate(**await _defect_payload(request))
    _ensure_failed_inspection(db, defect_data.inspection_id)
    defect = Defect(**defect_data.model_dump())
    _apply_resolution(defect, defect.status)
    db.add(defect); db.flush()
    log_activity(db, current_user, DEFECT_CREATED, "defect", defect.id, f"Created {defect.severity.lower()} defect #{defect.id} for inspection #{defect.inspection_id}", commit=False)
    db.commit(); db.refresh(defect)
    if _wants_html(request):
        return RedirectResponse(url=f"/inspections/{defect.inspection_id}", status_code=status.HTTP_303_SEE_OTHER)
    return defect


@router.get("", response_model=DefectList)
def list_defects(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))], search: str | None = None, defect_type: str | None = None, severity: str | None = None, status_filter: str | None = None, start_date: date | None = None, end_date: date | None = None, sort_by: str = "created_at", sort_order: str = "desc", page: int = 1, page_size: int | None = None, per_page: int = 10) -> DefectList | HTMLResponse:
    page, per_page = _pagination(page, per_page, page_size)
    query = _defect_query(search, defect_type, severity, status_filter, start_date, end_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(ceil(total / per_page), 1)
    sort_columns = {"id": Defect.id, "defect_type": Defect.defect_type, "severity": Defect.severity, "status": Defect.status, "created_at": Defect.created_at, "resolved_date": Defect.resolved_date}
    sort_column = sort_columns.get(sort_by, Defect.created_at)
    direction = sort_order.lower()
    order_by = sort_column.asc() if direction == "asc" else sort_column.desc()
    defects = list(db.scalars(query.order_by(order_by, Defect.id.desc()).offset((page - 1) * per_page).limit(per_page)).all())
    if _wants_html(request):
        return templates.TemplateResponse("defects/list.html", _template_context(request, current_user, defects=defects, search=search or "", defect_type=defect_type or "", severity=severity or "", status_filter=status_filter or "", start_date=start_date or "", end_date=end_date or "", page=page, per_page=per_page, total=total, pages=pages, sort_by=sort_by, sort_order=direction, page_size=per_page))
    return DefectList(items=defects, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/stats", response_model=DefectStats)
def defect_stats(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> DefectStats:
    by_type = {row[0]: row[1] for row in db.execute(select(Defect.defect_type, func.count(Defect.id)).group_by(Defect.defect_type)).all()}
    by_severity = {row[0]: row[1] for row in db.execute(select(Defect.severity, func.count(Defect.id)).group_by(Defect.severity)).all()}
    return DefectStats(by_type=by_type, by_severity=by_severity)


@router.get("/{defect_id}", response_model=DefectRead)
def get_defect(defect_id: int, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> Defect:
    return _get_defect_or_404(db, defect_id)


@router.get("/{defect_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_defect_page(defect_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    defect = _get_defect_or_404(db, defect_id)
    return templates.TemplateResponse("defects/form.html", _template_context(request, current_user, defect=defect, inspection=defect.inspection, form_action=f"/defects/{defect.id}/edit", form_title="Edit Defect"))


@router.put("/{defect_id}", response_model=DefectRead)
async def update_defect(defect_id: int, request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> Defect:
    defect = _get_defect_or_404(db, defect_id)
    updates = DefectUpdate(**await _defect_payload(request, partial=True)).model_dump(exclude_unset=True)
    if "inspection_id" in updates:
        _ensure_failed_inspection(db, updates["inspection_id"])
    if "status" in updates:
        _apply_resolution(defect, updates["status"])
    for field, value in updates.items():
        setattr(defect, field, value)
    log_activity(db, current_user, DEFECT_UPDATED, "defect", defect.id, f"Updated defect #{defect.id} for inspection #{defect.inspection_id}", commit=False)
    db.commit(); db.refresh(defect)
    return defect


@router.post("/{defect_id}/edit", include_in_schema=False)
async def update_defect_from_form(defect_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    defect = await update_defect(defect_id, request, db, current_user)
    return RedirectResponse(url=f"/inspections/{defect.inspection_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/{defect_id}", response_model=DefectRead)
def delete_defect(defect_id: int, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, INSPECTOR))]) -> Defect:
    defect = _get_defect_or_404(db, defect_id)
    db.delete(defect); db.commit()
    return defect


@router.post("/{defect_id}/delete", include_in_schema=False)
def delete_defect_from_form(defect_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    defect = _get_defect_or_404(db, defect_id)
    inspection_id = defect.inspection_id
    db.delete(defect); db.commit()
    return RedirectResponse(url=f"/inspections/{inspection_id}", status_code=status.HTTP_303_SEE_OTHER)
