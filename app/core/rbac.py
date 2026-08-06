"""Role-based access-control helpers for QualiTrack."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from app.models.factory import Batch, Defect, Inspection
from app.models.user import User

ROLE_ADMIN = "admin"
ROLE_QUALITY_MANAGER = "quality_manager"
ROLE_INSPECTOR = "inspector"
VALID_ROLES = (ROLE_ADMIN, ROLE_QUALITY_MANAGER, ROLE_INSPECTOR)
ROLE_LABELS = {
    ROLE_ADMIN: "Admin",
    ROLE_QUALITY_MANAGER: "Quality Manager",
    ROLE_INSPECTOR: "Inspector",
}


def normalize_role(role: str) -> str:
    """Normalize and validate a role value."""

    normalized = role.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid role")
    return normalized


def role_label(role: str) -> str:
    """Return a display label for a role."""

    return ROLE_LABELS.get(role, role.replace("_", " ").title())


def has_any_role(user: User | None, *roles: str) -> bool:
    """Return whether a user has any of the supplied roles."""

    return user is not None and user.role in roles


def can_manage_reference_data(user: User | None) -> bool:
    """Return whether a user may create/update/delete master data."""

    return has_any_role(user, ROLE_ADMIN)


def can_manage_quality(user: User | None) -> bool:
    """Return whether a user may manage inspections and defects."""

    return has_any_role(user, ROLE_ADMIN, ROLE_QUALITY_MANAGER, ROLE_INSPECTOR)


def can_view_reports(user: User | None) -> bool:
    """Return whether a user may view reports and analytics."""

    return has_any_role(user, ROLE_ADMIN, ROLE_QUALITY_MANAGER)


def can_manage_users(user: User | None) -> bool:
    """Return whether a user may manage users."""

    return has_any_role(user, ROLE_ADMIN)


def require_role(*roles: str) -> Callable:
    """Build a FastAPI dependency that requires one of the supplied roles."""

    from app.routers.auth import get_current_user

    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        return current_user

    return dependency



def ensure_inspection_access(user: User, inspection: Inspection) -> None:
    """Ensure an inspection is visible/manageable by the current user."""

    if user.role in {ROLE_ADMIN, ROLE_QUALITY_MANAGER}:
        return
    if user.role == ROLE_INSPECTOR and inspection.inspector_id == user.id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")


def ensure_batch_access(user: User, batch: Batch) -> None:
    """Ensure a batch is visible to the current user.

    The current schema has no user-to-production-line assignment column, so inspectors
    are allowed to view batch metadata needed to create their own inspections while
    write operations remain blocked.
    """

    if user.role in VALID_ROLES and batch is not None:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")


def ensure_defect_access(user: User, defect: Defect) -> None:
    """Ensure a defect is visible/manageable by the current user."""

    ensure_inspection_access(user, defect.inspection)


def rbac_template_context() -> dict[str, object]:
    """Return RBAC helpers exposed to Jinja templates."""

    return {
        "roles": ROLE_LABELS,
        "role_label": role_label,
        "can_manage_reference_data": can_manage_reference_data,
        "can_manage_quality": can_manage_quality,
        "can_view_reports": can_view_reports,
        "can_manage_users": can_manage_users,
    }
