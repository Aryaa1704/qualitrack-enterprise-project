"""Dashboard analytics routes for live quality metrics."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.models.activity import ActivityLog
from app.models.factory import Batch, Defect, Inspection
from app.models.user import User
from app.routers.auth import ADMIN, QUALITY_MANAGER, get_current_user, get_optional_current_user, redirect_if_forbidden, require_role

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def _today_iso() -> str:
    """Return today's date in UTC as an ISO string for SQLite date comparisons."""

    return datetime.now(timezone.utc).date().isoformat()


def _last_30_days() -> list[str]:
    """Return ISO date labels for the rolling 30-day dashboard window."""

    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(29, -1, -1)]


def _recent_activity(db: Session) -> list[ActivityLog]:
    """Return a small recent activity feed for the dashboard."""

    return list(db.scalars(select(ActivityLog).order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(8)).all())


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def dashboard_page(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Render the authenticated analytics dashboard shell."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    forbidden = redirect_if_forbidden(current_user, ADMIN, QUALITY_MANAGER)
    if forbidden is not None:
        return forbidden
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": current_user,
            "recent_activity": _recent_activity(db),
        },
    )


@router.get("/summary")
def dashboard_summary(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> dict[str, int | float]:
    """Return top-line dashboard quality metrics from live production data."""

    today = _today_iso()
    today_count = db.scalar(select(func.count(Inspection.id)).where(func.date(Inspection.inspection_date) == today)) or 0
    total_inspections = db.scalar(select(func.count(Inspection.id))) or 0
    pass_count = db.scalar(select(func.count(Inspection.id)).where(Inspection.overall_status == "Pass")) or 0
    fail_count = db.scalar(select(func.count(Inspection.id)).where(Inspection.overall_status == "Fail")) or 0
    pending_batches = db.scalar(select(func.count(Batch.id)).outerjoin(Inspection).where(Inspection.id.is_(None))) or 0
    critical_defects = db.scalar(select(func.count(Defect.id)).where(Defect.severity == "High", Defect.status != "Resolved")) or 0

    pass_percent = round((pass_count / total_inspections) * 100, 1) if total_inspections else 0.0
    fail_percent = round((fail_count / total_inspections) * 100, 1) if total_inspections else 0.0
    return {
        "today_inspections": today_count,
        "pass_percent": pass_percent,
        "fail_percent": fail_percent,
        "pending_inspections": pending_batches,
        "critical_defects": critical_defects,
    }


@router.get("/trend")
def dashboard_trend(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> dict[str, list[int] | list[str]]:
    """Return daily inspection counts for the last 30 days."""

    labels = _last_30_days()
    start_date = labels[0]
    rows = db.execute(
        select(func.date(Inspection.inspection_date), func.count(Inspection.id))
        .where(func.date(Inspection.inspection_date) >= start_date)
        .group_by(func.date(Inspection.inspection_date))
        .order_by(func.date(Inspection.inspection_date))
    ).all()
    counts_by_day = {row[0]: row[1] for row in rows}
    return {"labels": labels, "counts": [counts_by_day.get(label, 0) for label in labels]}


@router.get("/top-defects")
def dashboard_top_defects(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> dict[str, list[int] | list[str]]:
    """Return most common defect types for dashboard charting."""

    rows = db.execute(select(Defect.defect_type, func.count(Defect.id)).group_by(Defect.defect_type).order_by(func.count(Defect.id).desc(), Defect.defect_type).limit(8)).all()
    return {"labels": [row[0] for row in rows], "counts": [row[1] for row in rows]}


@router.get("/top-inspector")
def dashboard_top_inspector(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> dict[str, list[int] | list[str]]:
    """Return inspection counts grouped by inspector."""

    rows = db.execute(
        select(User.username, func.count(Inspection.id))
        .join(Inspection, Inspection.inspector_id == User.id)
        .group_by(User.id, User.username)
        .order_by(func.count(Inspection.id).desc(), User.username)
        .limit(8)
    ).all()
    return {"labels": [row[0] for row in rows], "counts": [row[1] for row in rows]}
