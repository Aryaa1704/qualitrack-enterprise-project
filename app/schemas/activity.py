"""Pydantic schemas for activity logs."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ActivityLogRead(BaseModel):
    """Activity log entry returned by the API."""

    id: int
    user_id: int
    action: str
    entity_type: str
    entity_id: int | None
    description: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActivityLogList(BaseModel):
    """Paginated activity log response."""

    items: list[ActivityLogRead]
    page: int
    per_page: int
    total: int
    pages: int
