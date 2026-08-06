"""Read-only reporting routes with CSV exports."""

from datetime import date
from io import StringIO
from math import ceil
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
import csv

from app.core.config import get_settings
from app.database.session import get_db
from app.models.factory import Batch, Defect, Factory, Inspection, Product, ProductionLine
from app.models.user import User
from app.routers.auth import ADMIN, QUALITY_MANAGER, require_role
from app.services.activity import REPORT_EXPORTED, log_activity

router = APIRouter(prefix="/reports", tags=["Reports"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def _pagination(page: int, per_page: int) -> tuple[int, int]:
    """Normalize report pagination inputs."""

    return max(page, 1), min(max(per_page, 1), 50)


def _report_context(request: Request, current_user: User, **extra: object) -> dict[str, object]:
    """Build common template context for report pages."""

    return {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, **extra}


def _csv_response(filename: str, headers: list[str], rows: list[list[Any]]) -> StreamingResponse:
    """Return a downloadable CSV response."""

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _inspection_query(product_id: int | None, batch_id: int | None, inspector_id: int | None, status_filter: str | None, start_date: date | None, end_date: date | None):
    query = select(Inspection).join(Batch).join(Product).join(User, Inspection.inspector_id == User.id)
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


def _inspection_payload(db: Session, product_id: int | None, batch_id: int | None, inspector_id: int | None, status_filter: str | None, start_date: date | None, end_date: date | None, page: int, per_page: int) -> dict[str, object]:
    page, per_page = _pagination(page, per_page)
    query = _inspection_query(product_id, batch_id, inspector_id, status_filter, start_date, end_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pass_count = db.scalar(select(func.count()).select_from(query.where(Inspection.overall_status == "Pass").subquery())) or 0
    fail_count = db.scalar(select(func.count()).select_from(query.where(Inspection.overall_status == "Fail").subquery())) or 0
    inspections = list(db.scalars(query.order_by(Inspection.inspection_date.desc(), Inspection.id.desc()).offset((page - 1) * per_page).limit(per_page)).all())
    return {"items": inspections, "summary": {"total": total, "pass_percent": round((pass_count / total) * 100, 1) if total else 0, "fail_percent": round((fail_count / total) * 100, 1) if total else 0}, "page": page, "per_page": per_page, "total": total, "pages": max(ceil(total / per_page), 1)}


def _defect_query(defect_type: str | None, severity: str | None, status_filter: str | None, start_date: date | None, end_date: date | None):
    query = select(Defect).join(Inspection)
    if defect_type:
        query = query.where(Defect.defect_type == defect_type.strip())
    if severity:
        query = query.where(Defect.severity == severity.strip().title())
    if status_filter:
        query = query.where(Defect.status == status_filter.strip().title())
    if start_date is not None:
        query = query.where(func.date(Defect.created_at) >= start_date.isoformat())
    if end_date is not None:
        query = query.where(func.date(Defect.created_at) <= end_date.isoformat())
    return query


def _defect_payload(db: Session, defect_type: str | None, severity: str | None, status_filter: str | None, start_date: date | None, end_date: date | None, page: int, per_page: int) -> dict[str, object]:
    page, per_page = _pagination(page, per_page)
    query = _defect_query(defect_type, severity, status_filter, start_date, end_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    open_count = db.scalar(select(func.count()).select_from(query.where(Defect.status == "Open").subquery())) or 0
    resolved_count = db.scalar(select(func.count()).select_from(query.where(Defect.status == "Resolved").subquery())) or 0
    critical_count = db.scalar(select(func.count()).select_from(query.where(Defect.severity == "High").subquery())) or 0
    defects = list(db.scalars(query.order_by(Defect.created_at.desc(), Defect.id.desc()).offset((page - 1) * per_page).limit(per_page)).all())
    return {"items": defects, "summary": {"open": open_count, "resolved": resolved_count, "critical": critical_count}, "page": page, "per_page": per_page, "total": total, "pages": max(ceil(total / per_page), 1)}


def _factory_rows(db: Session) -> list[dict[str, object]]:
    pass_count = func.sum(case((Inspection.overall_status == "Pass", 1), else_=0))
    fail_count = func.sum(case((Inspection.overall_status == "Fail", 1), else_=0))
    rows = db.execute(select(Factory.id, Factory.name, Factory.code, func.count(Inspection.id), pass_count, fail_count).join(ProductionLine, ProductionLine.factory_id == Factory.id, isouter=True).join(Batch, Batch.production_line_id == ProductionLine.id, isouter=True).join(Inspection, Inspection.batch_id == Batch.id, isouter=True).group_by(Factory.id).order_by(Factory.name)).all()
    return [{"factory_id": row[0], "factory_name": row[1], "factory_code": row[2], "total_inspections": row[3] or 0, "pass_count": row[4] or 0, "fail_count": row[5] or 0} for row in rows]


def _batch_rows(db: Session) -> list[dict[str, object]]:
    rows = db.execute(select(Batch.id, Batch.batch_number, Product.name, func.count(func.distinct(Inspection.id)), func.count(Defect.id)).join(Product, Batch.product_id == Product.id).join(Inspection, Inspection.batch_id == Batch.id, isouter=True).join(Defect, Defect.inspection_id == Inspection.id, isouter=True).group_by(Batch.id).order_by(Batch.manufacturing_date.desc(), Batch.id.desc())).all()
    return [{"batch_id": row[0], "batch_number": row[1], "product_name": row[2], "inspection_count": row[3] or 0, "defect_count": row[4] or 0} for row in rows]


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def reports_page(request: Request, current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> HTMLResponse:
    return templates.TemplateResponse("reports/index.html", _report_context(request, current_user))


@router.get("/inspection", response_model=None)
def inspection_report(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))], product_id: int | None = None, batch_id: int | None = None, inspector_id: int | None = None, status_filter: str | None = None, start_date: date | None = None, end_date: date | None = None, page: int = 1, per_page: int = 10) -> dict[str, object] | HTMLResponse:
    data = _inspection_payload(db, product_id, batch_id, inspector_id, status_filter, start_date, end_date, page, per_page)
    if "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse("reports/inspection.html", _report_context(request, current_user, **data, products=list(db.scalars(select(Product).order_by(Product.name)).all()), batches=list(db.scalars(select(Batch).order_by(Batch.batch_number)).all()), inspectors=list(db.scalars(select(User).order_by(User.username)).all()), product_id=product_id or "", batch_id=batch_id or "", inspector_id=inspector_id or "", status_filter=status_filter or "", start_date=start_date or "", end_date=end_date or ""))
    return data


@router.get("/inspection/export")
def inspection_report_export(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))], product_id: int | None = None, batch_id: int | None = None, inspector_id: int | None = None, status_filter: str | None = None, start_date: date | None = None, end_date: date | None = None) -> StreamingResponse:
    inspections = list(db.scalars(_inspection_query(product_id, batch_id, inspector_id, status_filter, start_date, end_date).order_by(Inspection.inspection_date.desc(), Inspection.id.desc())).all())
    rows = [[item.id, item.inspection_date, item.batch.batch_number, item.batch.product.name, item.inspector.username, item.overall_status, item.inspection_score] for item in inspections]
    log_activity(db, current_user, REPORT_EXPORTED, "report", None, "Exported inspection report")
    return _csv_response("inspection-report.csv", ["Inspection ID", "Date", "Batch", "Product", "Inspector", "Status", "Score"], rows)


@router.get("/defect", response_model=None)
def defect_report(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))], defect_type: str | None = None, severity: str | None = None, status_filter: str | None = None, start_date: date | None = None, end_date: date | None = None, page: int = 1, per_page: int = 10) -> dict[str, object] | HTMLResponse:
    data = _defect_payload(db, defect_type, severity, status_filter, start_date, end_date, page, per_page)
    if "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse("reports/defect.html", _report_context(request, current_user, **data, defect_type=defect_type or "", severity=severity or "", status_filter=status_filter or "", start_date=start_date or "", end_date=end_date or ""))
    return data


@router.get("/defect/export")
def defect_report_export(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))], defect_type: str | None = None, severity: str | None = None, status_filter: str | None = None, start_date: date | None = None, end_date: date | None = None) -> StreamingResponse:
    defects = list(db.scalars(_defect_query(defect_type, severity, status_filter, start_date, end_date).order_by(Defect.created_at.desc(), Defect.id.desc())).all())
    rows = [[item.id, item.created_at, item.inspection_id, item.defect_type, item.severity, item.status, item.description] for item in defects]
    log_activity(db, current_user, REPORT_EXPORTED, "report", None, "Exported defect report")
    return _csv_response("defect-report.csv", ["Defect ID", "Created", "Inspection ID", "Type", "Severity", "Status", "Description"], rows)


@router.get("/factory", response_model=None)
def factory_report(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> dict[str, object] | HTMLResponse:
    rows = _factory_rows(db)
    data = {"items": rows, "summary": {"factories": len(rows), "pass_count": sum(int(row["pass_count"]) for row in rows), "fail_count": sum(int(row["fail_count"]) for row in rows)}}
    if "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse("reports/factory.html", _report_context(request, current_user, **data))
    return data


@router.get("/factory/export")
def factory_report_export(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> StreamingResponse:
    rows = [[row["factory_id"], row["factory_name"], row["factory_code"], row["total_inspections"], row["pass_count"], row["fail_count"]] for row in _factory_rows(db)]
    log_activity(db, current_user, REPORT_EXPORTED, "report", None, "Exported factory report")
    return _csv_response("factory-report.csv", ["Factory ID", "Factory", "Code", "Total Inspections", "Pass", "Fail"], rows)


@router.get("/batch", response_model=None)
def batch_report(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> dict[str, object] | HTMLResponse:
    rows = _batch_rows(db)
    data = {"items": rows, "summary": {"batches": len(rows), "inspection_count": sum(int(row["inspection_count"]) for row in rows), "defect_count": sum(int(row["defect_count"]) for row in rows)}}
    if "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse("reports/batch.html", _report_context(request, current_user, **data))
    return data


@router.get("/batch/export")
def batch_report_export(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> StreamingResponse:
    rows = [[row["batch_id"], row["batch_number"], row["product_name"], row["inspection_count"], row["defect_count"]] for row in _batch_rows(db)]
    log_activity(db, current_user, REPORT_EXPORTED, "report", None, "Exported batch report")
    return _csv_response("batch-report.csv", ["Batch ID", "Batch", "Product", "Inspections", "Defects"], rows)
