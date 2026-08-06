"""Activity log and notification routes."""

from datetime import date
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.models.activity import ActivityLog
from app.models.user import User
from app.routers.auth import ADMIN, QUALITY_MANAGER, require_role
from app.schemas.activity import ActivityLogList, ActivityLogRead
from app.services.activity import ACTION_CHOICES, recent_activity_query

router = APIRouter(prefix="/activity-logs", tags=["Activity Logs"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def _pagination(page: int, per_page: int) -> tuple[int, int]:
    return max(page, 1), min(max(per_page, 1), 50)


def _activity_query(user_id: int | None, action: str | None, start_date: date | None, end_date: date | None):
    query = select(ActivityLog).join(User)
    if user_id is not None:
        query = query.where(ActivityLog.user_id == user_id)
    if action:
        query = query.where(ActivityLog.action == action.strip())
    if start_date is not None:
        query = query.where(func.date(ActivityLog.created_at) >= start_date.isoformat())
    if end_date is not None:
        query = query.where(func.date(ActivityLog.created_at) <= end_date.isoformat())
    return query


@router.get("", response_model=ActivityLogList)
def list_activity_logs(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))], user_id: int | None = None, action: str | None = None, start_date: date | None = None, end_date: date | None = None, page: int = 1, per_page: int = 10) -> ActivityLogList | HTMLResponse:
    page, per_page = _pagination(page, per_page)
    query = _activity_query(user_id, action, start_date, end_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(ceil(total / per_page), 1)
    items = list(db.scalars(query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).offset((page - 1) * per_page).limit(per_page)).all())
    if "text/html" in request.headers.get("accept", ""):
        users = list(db.scalars(select(User).order_by(User.username)).all())
        return templates.TemplateResponse(
            "activity-logs/list.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "app_description": settings.app_description,
                "current_user": current_user,
                "items": items,
                "users": users,
                "action_choices": ACTION_CHOICES,
                "user_id": user_id or "",
                "action": action or "",
                "start_date": start_date or "",
                "end_date": end_date or "",
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": pages,
            },
        )
    return ActivityLogList(items=items, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/recent", response_model=list[ActivityLogRead])
def recent_activity_logs(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER, "inspector"))], limit: int = 8):
    limit = min(max(limit, 1), 20)
    return list(db.scalars(recent_activity_query(current_user).limit(limit)).all())
