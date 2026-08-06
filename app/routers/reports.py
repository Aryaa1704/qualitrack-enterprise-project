"""Reporting routes and CSV exports for QualiTrack."""

from collections.abc import Iterable
from datetime import date
from io import StringIO
from math import ceil
from typing import Annotated, Any
from urllib.parse import urlencode
import csv

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.models.factory import Batch, Defect, Factory, Inspection, Product, ProductionLine
from app.models.user import User
from app.routers.auth import get_current_user, get_optional_current_user
from app.routers.defects import DEFECT_STATUSES, DEFECT_TYPES, SEVERITIES

router = APIRouter(prefix="/reports", tags=["Reports"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
REPORT_PER_PAGE = 10


def _pagination(page: int, per_page: int) -> tuple[int, int]:
    return max(page, 1), min(max(per_page, 1), 50)


def _pages(total: int, per_page: int) -> int:
    return max(ceil(total / per_page), 1)


def _template_context(request: Request, current_user: User, **extra: object) -> dict[str, object]:
    return {
        "request": request,
        "app_name": settings.app_name,
        "app_description": settings.app_description,
        "current_user": current_user,
        **extra,
    }


def _auth_user_or_redirect(request: Request, db: Session) -> User | Response:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    return current_user


def _export_query(**params: object) -> str:
    filtered = {key: value for key, value in params.items() if value not in (None, "")}
    return urlencode(filtered)


def _csv_response(filename: str, headers: list[str], rows: Iterable[Iterable[object]]) -> Response:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _form_options(db: Session) -> dict[str, list[Any]]:
    return {
        "products": list(db.scalars(select(Product).order_by(Product.name)).all()),
        "batches": list(db.scalars(select(Batch).order_by(Batch.batch_number)).all()),
        "inspectors": list(db.scalars(select(User).order_by(User.username)).all()),
    }


def _inspection_rows_query(
    product_id: int | None,
    batch_id: int | None,
    inspector_id: int | None,
    status_filter: str | None,
    start_date: date | None,
    end_date: date | None,
):
    query = (
        select(
            Inspection.id.label("inspection_id"),
            Inspection.inspection_date,
            Product.name.label("product_name"),
            Batch.batch_number,
            User.username.label("inspector_name"),
            Inspection.overall_status,
            Inspection.inspection_score,
        )
        .join(Batch, Inspection.batch_id == Batch.id)
        .join(Product, Batch.product_id == Product.id)
        .join(User, Inspection.inspector_id == User.id)
    )
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


def _inspection_report(
    db: Session,
    product_id: int | None = None,
    batch_id: int | None = None,
    inspector_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = REPORT_PER_PAGE,
) -> dict[str, object]:
    page, per_page = _pagination(page, per_page)
    query = _inspection_rows_query(product_id, batch_id, inspector_id, status_filter, start_date, end_date)
    subquery = query.subquery()
    total = db.scalar(select(func.count()).select_from(subquery)) or 0
    pass_count = db.scalar(select(func.count()).select_from(subquery).where(subquery.c.overall_status == "Pass")) or 0
    fail_count = db.scalar(select(func.count()).select_from(subquery).where(subquery.c.overall_status == "Fail")) or 0
    rows = db.execute(query.order_by(Inspection.inspection_date.desc(), Inspection.id.desc()).offset((page - 1) * per_page).limit(per_page)).mappings().all()
    return {
        "items": [dict(row) for row in rows],
        "summary": {
            "total": total,
            "pass_percent": round((pass_count / total) * 100, 1) if total else 0.0,
            "fail_percent": round((fail_count / total) * 100, 1) if total else 0.0,
        },
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": _pages(total, per_page),
    }


def _defect_rows_query(defect_type: str | None, severity: str | None, status_filter: str | None, start_date: date | None, end_date: date | None):
    query = (
        select(
            Defect.id.label("defect_id"),
            Defect.created_at,
            Defect.defect_type,
            Defect.severity,
            Defect.status,
            Defect.description,
            Inspection.id.label("inspection_id"),
            Batch.batch_number,
        )
        .join(Inspection, Defect.inspection_id == Inspection.id)
        .join(Batch, Inspection.batch_id == Batch.id)
    )
    if defect_type:
        query = query.where(Defect.defect_type == defect_type)
    if severity:
        query = query.where(Defect.severity == severity)
    if status_filter:
        query = query.where(Defect.status == status_filter)
    if start_date is not None:
        query = query.where(func.date(Defect.created_at) >= start_date.isoformat())
    if end_date is not None:
        query = query.where(func.date(Defect.created_at) <= end_date.isoformat())
    return query


def _defect_report(
    db: Session,
    defect_type: str | None = None,
    severity: str | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = REPORT_PER_PAGE,
) -> dict[str, object]:
    page, per_page = _pagination(page, per_page)
    query = _defect_rows_query(defect_type, severity, status_filter, start_date, end_date)
    subquery = query.subquery()
    total = db.scalar(select(func.count()).select_from(subquery)) or 0
    open_count = db.scalar(select(func.count()).select_from(subquery).where(subquery.c.status != "Resolved")) or 0
    resolved_count = db.scalar(select(func.count()).select_from(subquery).where(subquery.c.status == "Resolved")) or 0
    critical_count = db.scalar(select(func.count()).select_from(subquery).where(subquery.c.severity == "High", subquery.c.status != "Resolved")) or 0
    rows = db.execute(query.order_by(Defect.created_at.desc(), Defect.id.desc()).offset((page - 1) * per_page).limit(per_page)).mappings().all()
    return {
        "items": [dict(row) for row in rows],
        "summary": {"total": total, "open": open_count, "resolved": resolved_count, "critical": critical_count},
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": _pages(total, per_page),
    }


def _factory_report(db: Session, page: int = 1, per_page: int = REPORT_PER_PAGE) -> dict[str, object]:
    page, per_page = _pagination(page, per_page)
    query = (
        select(
            Factory.id.label("factory_id"),
            Factory.name.label("factory_name"),
            Factory.code.label("factory_code"),
            func.count(Inspection.id).label("inspection_count"),
            func.sum(case((Inspection.overall_status == "Pass", 1), else_=0)).label("pass_count"),
            func.sum(case((Inspection.overall_status == "Fail", 1), else_=0)).label("fail_count"),
        )
        .outerjoin(ProductionLine, ProductionLine.factory_id == Factory.id)
        .outerjoin(Batch, Batch.production_line_id == ProductionLine.id)
        .outerjoin(Inspection, Inspection.batch_id == Batch.id)
        .group_by(Factory.id, Factory.name, Factory.code)
        .order_by(Factory.name)
    )
    total = db.scalar(select(func.count()).select_from(Factory)) or 0
    rows = db.execute(query.offset((page - 1) * per_page).limit(per_page)).mappings().all()
    return {
        "items": [dict(row) for row in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": _pages(total, per_page),
    }


def _batch_rows_query(product_id: int | None, batch_id: int | None, status_filter: str | None, start_date: date | None, end_date: date | None):
    query = (
        select(
            Batch.id.label("batch_id"),
            Batch.batch_number,
            Product.name.label("product_name"),
            Batch.manufacturing_date,
            Batch.status,
            func.count(func.distinct(Inspection.id)).label("inspection_count"),
            func.sum(case((Inspection.overall_status == "Pass", 1), else_=0)).label("pass_count"),
            func.sum(case((Inspection.overall_status == "Fail", 1), else_=0)).label("fail_count"),
            func.count(func.distinct(Defect.id)).label("defect_count"),
        )
        .join(Product, Batch.product_id == Product.id)
        .outerjoin(Inspection, Inspection.batch_id == Batch.id)
        .outerjoin(Defect, Defect.inspection_id == Inspection.id)
        .group_by(Batch.id, Batch.batch_number, Product.name, Batch.manufacturing_date, Batch.status)
        .order_by(Batch.manufacturing_date.desc(), Batch.id.desc())
    )
    if product_id is not None:
        query = query.where(Batch.product_id == product_id)
    if batch_id is not None:
        query = query.where(Batch.id == batch_id)
    if status_filter:
        query = query.where(Batch.status == status_filter)
    if start_date is not None:
        query = query.where(Batch.manufacturing_date >= start_date)
    if end_date is not None:
        query = query.where(Batch.manufacturing_date <= end_date)
    return query


def _batch_report(
    db: Session,
    product_id: int | None = None,
    batch_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = REPORT_PER_PAGE,
) -> dict[str, object]:
    page, per_page = _pagination(page, per_page)
    query = _batch_rows_query(product_id, batch_id, status_filter, start_date, end_date)
    subquery = query.subquery()
    total = db.scalar(select(func.count()).select_from(subquery)) or 0
    inspection_total = db.scalar(select(func.sum(subquery.c.inspection_count)).select_from(subquery)) or 0
    defect_total = db.scalar(select(func.sum(subquery.c.defect_count)).select_from(subquery)) or 0
    rows = db.execute(query.offset((page - 1) * per_page).limit(per_page)).mappings().all()
    return {
        "items": [dict(row) for row in rows],
        "summary": {"batches": total, "inspections": inspection_total, "defects": defect_total},
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": _pages(total, per_page),
    }


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def reports_index(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    current_user = _auth_user_or_redirect(request, db)
    if isinstance(current_user, Response):
        return current_user
    return templates.TemplateResponse("reports/index.html", _template_context(request, current_user))


@router.get("/inspection", response_class=HTMLResponse, include_in_schema=False)
def inspection_report_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    product_id: int | None = None,
    batch_id: int | None = None,
    inspector_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = REPORT_PER_PAGE,
) -> Response:
    current_user = _auth_user_or_redirect(request, db)
    if isinstance(current_user, Response):
        return current_user
    report = _inspection_report(db, product_id, batch_id, inspector_id, status_filter, start_date, end_date, page, per_page)
    return templates.TemplateResponse(
        "reports/inspection.html",
        _template_context(
            request,
            current_user,
            report=report,
            status_filter=status_filter or "",
            start_date=start_date or "",
            end_date=end_date or "",
            product_id=product_id or "",
            batch_id=batch_id or "",
            inspector_id=inspector_id or "",
            export_query=_export_query(product_id=product_id, batch_id=batch_id, inspector_id=inspector_id, status_filter=status_filter, start_date=start_date, end_date=end_date),
            **_form_options(db),
        ),
    )


@router.get("/inspection/data")
def inspection_report_data(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    product_id: int | None = None,
    batch_id: int | None = None,
    inspector_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = REPORT_PER_PAGE,
) -> dict[str, object]:
    return _inspection_report(db, product_id, batch_id, inspector_id, status_filter, start_date, end_date, page, per_page)


@router.get("/inspection/export")
def inspection_report_export(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    product_id: int | None = None,
    batch_id: int | None = None,
    inspector_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Response:
    rows = db.execute(_inspection_rows_query(product_id, batch_id, inspector_id, status_filter, start_date, end_date).order_by(Inspection.inspection_date.desc(), Inspection.id.desc())).mappings().all()
    return _csv_response("inspection-report.csv", ["Inspection ID", "Date", "Product", "Batch", "Inspector", "Status", "Score"], ([row["inspection_id"], row["inspection_date"], row["product_name"], row["batch_number"], row["inspector_name"], row["overall_status"], row["inspection_score"]] for row in rows))


@router.get("/defect", response_class=HTMLResponse, include_in_schema=False)
def defect_report_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    defect_type: str | None = None,
    severity: str | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = REPORT_PER_PAGE,
) -> Response:
    current_user = _auth_user_or_redirect(request, db)
    if isinstance(current_user, Response):
        return current_user
    report = _defect_report(db, defect_type, severity, status_filter, start_date, end_date, page, per_page)
    return templates.TemplateResponse(
        "reports/defect.html",
        _template_context(
            request,
            current_user,
            report=report,
            defect_types=DEFECT_TYPES,
            severities=SEVERITIES,
            defect_statuses=DEFECT_STATUSES,
            defect_type=defect_type or "",
            severity=severity or "",
            status_filter=status_filter or "",
            start_date=start_date or "",
            end_date=end_date or "",
            export_query=_export_query(defect_type=defect_type, severity=severity, status_filter=status_filter, start_date=start_date, end_date=end_date),
        ),
    )


@router.get("/defect/data")
def defect_report_data(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    defect_type: str | None = None,
    severity: str | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = REPORT_PER_PAGE,
) -> dict[str, object]:
    return _defect_report(db, defect_type, severity, status_filter, start_date, end_date, page, per_page)


@router.get("/defect/export")
def defect_report_export(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    defect_type: str | None = None,
    severity: str | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Response:
    rows = db.execute(_defect_rows_query(defect_type, severity, status_filter, start_date, end_date).order_by(Defect.created_at.desc(), Defect.id.desc())).mappings().all()
    return _csv_response("defect-report.csv", ["Defect ID", "Created", "Inspection ID", "Batch", "Type", "Severity", "Status", "Description"], ([row["defect_id"], row["created_at"], row["inspection_id"], row["batch_number"], row["defect_type"], row["severity"], row["status"], row["description"]] for row in rows))


@router.get("/factory", response_class=HTMLResponse, include_in_schema=False)
def factory_report_page(request: Request, db: Annotated[Session, Depends(get_db)], page: int = 1, per_page: int = REPORT_PER_PAGE) -> Response:
    current_user = _auth_user_or_redirect(request, db)
    if isinstance(current_user, Response):
        return current_user
    return templates.TemplateResponse("reports/factory.html", _template_context(request, current_user, report=_factory_report(db, page, per_page)))


@router.get("/factory/data")
def factory_report_data(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)], page: int = 1, per_page: int = REPORT_PER_PAGE) -> dict[str, object]:
    return _factory_report(db, page, per_page)


@router.get("/factory/export")
def factory_report_export(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)]) -> Response:
    rows = _factory_report(db, page=1, per_page=10000)["items"]
    return _csv_response("factory-report.csv", ["Factory ID", "Factory", "Code", "Inspections", "Pass", "Fail"], ([row["factory_id"], row["factory_name"], row["factory_code"], row["inspection_count"], row["pass_count"] or 0, row["fail_count"] or 0] for row in rows))


@router.get("/batch", response_class=HTMLResponse, include_in_schema=False)
def batch_report_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    product_id: int | None = None,
    batch_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = REPORT_PER_PAGE,
) -> Response:
    current_user = _auth_user_or_redirect(request, db)
    if isinstance(current_user, Response):
        return current_user
    report = _batch_report(db, product_id, batch_id, status_filter, start_date, end_date, page, per_page)
    return templates.TemplateResponse(
        "reports/batch.html",
        _template_context(
            request,
            current_user,
            report=report,
            product_id=product_id or "",
            batch_id=batch_id or "",
            status_filter=status_filter or "",
            start_date=start_date or "",
            end_date=end_date or "",
            export_query=_export_query(product_id=product_id, batch_id=batch_id, status_filter=status_filter, start_date=start_date, end_date=end_date),
            **_form_options(db),
        ),
    )


@router.get("/batch/data")
def batch_report_data(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    product_id: int | None = None,
    batch_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
    per_page: int = REPORT_PER_PAGE,
) -> dict[str, object]:
    return _batch_report(db, product_id, batch_id, status_filter, start_date, end_date, page, per_page)


@router.get("/batch/export")
def batch_report_export(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    product_id: int | None = None,
    batch_id: int | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Response:
    rows = db.execute(_batch_rows_query(product_id, batch_id, status_filter, start_date, end_date)).mappings().all()
    return _csv_response("batch-report.csv", ["Batch ID", "Batch", "Product", "Manufacturing Date", "Status", "Inspections", "Pass", "Fail", "Defects"], ([row["batch_id"], row["batch_number"], row["product_name"], row["manufacturing_date"], row["status"], row["inspection_count"], row["pass_count"] or 0, row["fail_count"] or 0, row["defect_count"]] for row in rows))
