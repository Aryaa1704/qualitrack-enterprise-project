"""Authentication routes and dependencies."""

from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordBearer
from fastapi.templating import Jinja2Templates
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.models.user import User
from app.schemas.user import Token, UserRead, UserRoleUpdate
from app.services.activity import LOGIN, log_activity
from app.services.auth import create_access_token, decode_access_token, get_password_hash, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

VALID_ROLES = ("admin", "quality_manager", "inspector")
ADMIN = "admin"
QUALITY_MANAGER = "quality_manager"
INSPECTOR = "inspector"
ROLE_LABELS = {ADMIN: "Admin", QUALITY_MANAGER: "Quality Manager", INSPECTOR: "Inspector"}


def normalize_role(role: str | None) -> str:
    """Normalize and validate a role value."""

    role_value = (role or INSPECTOR).strip().lower().replace("-", "_").replace(" ", "_")
    if role_value not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid role")
    return role_value


def role_label(role: str) -> str:
    """Return a display label for a role."""

    return ROLE_LABELS.get(role, role.replace("_", " ").title())


def require_role(*allowed_roles: str):
    """Return a dependency requiring the current user to have one of the allowed roles."""

    normalized_allowed = {normalize_role(role) for role in allowed_roles}

    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in normalized_allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        return current_user

    return dependency


def redirect_if_forbidden(user: User, *allowed_roles: str) -> RedirectResponse | None:
    """Return a not-authorized redirect when a user lacks one of the allowed roles."""

    if user.role not in {normalize_role(role) for role in allowed_roles}:
        return RedirectResponse(url="/auth/not-authorized", status_code=status.HTTP_303_SEE_OTHER)
    return None


def get_user_by_username(db: Session, username: str) -> User | None:
    """Return a user by username."""

    return db.scalar(select(User).where(User.username == username))


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> User:
    """Return the authenticated user or raise an API authentication error."""

    access_token = token or request.cookies.get("access_token")
    if access_token and access_token.startswith("Bearer "):
        access_token = access_token.removeprefix("Bearer ")

    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    username = decode_access_token(access_token)
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = get_user_by_username(db, username)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or missing user")

    return user


def get_optional_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User | None:
    """Return the authenticated user when a valid auth cookie is present."""

    access_token = request.cookies.get("access_token")
    if access_token and access_token.startswith("Bearer "):
        access_token = access_token.removeprefix("Bearer ")
    if not access_token:
        return None

    username = decode_access_token(access_token)
    if username is None:
        return None
    user = get_user_by_username(db, username)
    if user is None or not user.is_active:
        return None
    return user


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
def register_page(request: Request) -> HTMLResponse:
    """Render the registration page."""

    return templates.TemplateResponse(
        "register.html",
        {"request": request, "app_name": settings.app_name, "app_description": settings.app_description},
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User | RedirectResponse:
    """Create a user account with the default inspector role."""

    form_data = parse_qs((await request.body()).decode("utf-8"))
    username = form_data.get("username", [""])[0].strip()
    email = form_data.get("email", [""])[0].strip()
    password = form_data.get("password", [""])[0]
    role = normalize_role(form_data.get("role", ["inspector"])[0])
    if len(username) < 3 or len(username) > 50 or len(password) < 8 or len(password) > 128:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid registration data")
    try:
        email = validate_email(email).normalized
    except EmailNotValidError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid registration data"
        ) from exc

    existing_user = db.scalar(select(User).where(or_(User.username == username, User.email == email)))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username or email already registered")

    user = User(username=username, email=email, hashed_password=get_password_hash(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    return user


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request) -> HTMLResponse:
    """Render the login page."""

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "app_name": settings.app_name, "app_description": settings.app_description},
    )


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> Token | RedirectResponse:
    """Authenticate a user and issue a JWT access token."""

    form_data = parse_qs((await request.body()).decode("utf-8"))
    username = form_data.get("username", [""])[0].strip()
    password = form_data.get("password", [""])[0]

    user = get_user_by_username(db, username)
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")

    log_activity(db, user, LOGIN, "user", user.id, f"{user.username} logged in")
    access_token = create_access_token(user.username)
    if "text/html" in request.headers.get("accept", ""):
        redirect = RedirectResponse(url="/auth/profile", status_code=status.HTTP_303_SEE_OTHER)
        redirect.set_cookie(
            key="access_token",
            value=f"Bearer {access_token}",
            httponly=True,
            samesite="lax",
            max_age=settings.access_token_expire_minutes * 60,
            # Set secure=True in production (HTTPS only).
            secure=False,
        )
        return redirect

    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        # Set secure=True in production (HTTPS only).
        secure=False,
    )
    return Token(access_token=access_token)


@router.get("/me", response_model=UserRead)
def read_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """Return the current authenticated user's profile details."""

    return current_user


@router.post("/logout")
def logout() -> RedirectResponse:
    """Clear the auth cookie and redirect to the login page."""

    response = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response


@router.get("/profile", response_class=HTMLResponse, include_in_schema=False)
def profile_page(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Render the current user's profile page or redirect anonymous visitors."""

    user = get_optional_current_user(request, db)
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": user,
        },
    )


@router.get("/not-authorized", response_class=HTMLResponse, include_in_schema=False)
def not_authorized_page(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Render a friendly forbidden-access page."""

    user = get_optional_current_user(request, db)
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "not_authorized.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": user,
        },
        status_code=status.HTTP_403_FORBIDDEN,
    )


@router.get("/users", response_class=HTMLResponse, include_in_schema=False)
def manage_users_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> HTMLResponse:
    """Render the admin-only user management page."""

    users = list(db.scalars(select(User).order_by(User.username)).all())
    return templates.TemplateResponse(
        "users/manage.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": current_user,
            "users": users,
            "roles": VALID_ROLES,
            "role_labels": ROLE_LABELS,
        },
    )


@router.put("/users/{user_id}/role", response_model=UserRead)
async def update_user_role(
    user_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> User:
    """Change a user's role; admin only."""

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


@router.post("/users/{user_id}/role", include_in_schema=False)
async def update_user_role_from_form(
    user_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> RedirectResponse:
    """Change a user's role from the admin HTML form."""

    await update_user_role(user_id, request, db, current_user)
    return RedirectResponse(url="/auth/users", status_code=status.HTTP_303_SEE_OTHER)
