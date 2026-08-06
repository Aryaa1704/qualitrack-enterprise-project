"""Administrative user management routes."""

from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rbac import ROLE_ADMIN, VALID_ROLES, normalize_role, require_role, rbac_template_context
from app.database.session import get_db
from app.models.user import User
from app.schemas.user import UserRead, UserRoleUpdate

router = APIRouter(prefix="/users", tags=["Users"])
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update(rbac_template_context())
settings = get_settings()


@router.get("/manage", response_class=HTMLResponse, include_in_schema=False)
def manage_users_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ROLE_ADMIN))],
) -> HTMLResponse:
    """Render the admin-only user role management page."""

    users = list(db.scalars(select(User).order_by(User.username)).all())
    return templates.TemplateResponse(
        "users/manage.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": current_user,
            "users": users,
            "valid_roles": VALID_ROLES,
        },
    )


@router.put("/{user_id}/role", response_model=UserRead)
async def update_user_role(
    user_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ROLE_ADMIN))],
) -> User:
    """Update a user's role."""

    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if "application/json" in request.headers.get("content-type", ""):
        payload = await request.json()
    else:
        form_data = parse_qs((await request.body()).decode("utf-8"))
        payload = {key: values[0] for key, values in form_data.items() if values}
    role_update = UserRoleUpdate(**payload)
    target_user.role = normalize_role(role_update.role)
    db.commit()
    db.refresh(target_user)
    return target_user


@router.post("/{user_id}/role", include_in_schema=False)
async def update_user_role_from_form(
    user_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ROLE_ADMIN))],
) -> RedirectResponse:
    """Update a user's role from the admin page."""

    await update_user_role(user_id, request, db, current_user)
    return RedirectResponse(url="/users/manage", status_code=status.HTTP_303_SEE_OTHER)
