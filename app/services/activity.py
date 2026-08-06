"""Helpers for writing and reading activity log events."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import ActivityLog
from app.models.user import User

LOGIN = "login"
INSPECTION_CREATED = "inspection_created"
INSPECTION_UPDATED = "inspection_updated"
DEFECT_CREATED = "defect_created"
DEFECT_UPDATED = "defect_updated"
REPORT_EXPORTED = "report_exported"
ACTION_CHOICES = (LOGIN, INSPECTION_CREATED, INSPECTION_UPDATED, DEFECT_CREATED, DEFECT_UPDATED, REPORT_EXPORTED)


def log_activity(db: Session, user: User, action: str, entity_type: str, entity_id: int | None, description: str, *, commit: bool = True) -> ActivityLog:
    """Persist an activity log entry for a completed user action."""

    log = ActivityLog(user_id=user.id, action=action, entity_type=entity_type, entity_id=entity_id, description=description)
    db.add(log)
    if commit:
        db.commit()
        db.refresh(log)
    return log


def recent_activity_query(user: User):
    """Return the query for activity relevant to the logged-in user."""

    query = select(ActivityLog)
    if user.role == "inspector":
        query = query.where(ActivityLog.user_id == user.id)
    return query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
