"""Authentication routes and dependencies."""

from datetime import datetime, timedelta, timezone
import hmac
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
from app.services.otp import generate_otp, otp_digest, send_otp_email
import jwt

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

    return templates.TemplateResponse(request,
        "register.html",
        {"request": request, "app_name": settings.app_name, "app_description": settings.app_description},
    )


def _pending_registration_token(username: str, email: str, password_hash: str, role: str, otp: str) -> str:
    payload = {
        "type": "registration_pending",
        "sub": username,
        "email": email,
        "password_hash": password_hash,
        "role": role,
        "digest": otp_digest(username, otp),
        "attempts": 0,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def _decode_pending_registration(token: str) -> dict[str, object] | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm], leeway=0)
    except jwt.InvalidTokenError:
        return None
    if payload.get("type") != "registration_pending":
        return None
    return payload


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

    if "text/html" in request.headers.get("accept", ""):
        otp = generate_otp()
        try:
            send_otp_email(email, otp)
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        pending = _pending_registration_token(username, email, get_password_hash(password), role, otp)
        redirect = RedirectResponse(url="/auth/verify-registration", status_code=status.HTTP_303_SEE_OTHER)
        redirect.set_cookie("pending_registration", pending, httponly=True, samesite="lax", max_age=settings.otp_expire_minutes * 60, secure=False)
        return redirect
    user = User(username=username, email=email, hashed_password=get_password_hash(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request) -> HTMLResponse:
    """Render the login page."""

    return templates.TemplateResponse(request,
        "login.html",
        {"request": request, "app_name": settings.app_name, "app_description": settings.app_description},
    )


@router.get("/verify-registration", response_class=HTMLResponse, include_in_schema=False)
def verify_registration_page(request: Request) -> Response:
    """Render the email verification form for a new registration."""

    if not request.cookies.get("pending_registration"):
        return RedirectResponse(url="/auth/register", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "verify-registration.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description})


@router.post("/verify-registration", include_in_schema=False)
async def verify_registration(request: Request, response: Response, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    """Create the account only after the submitted email OTP is valid."""

    pending = _decode_pending_registration(request.cookies.get("pending_registration", ""))
    if pending is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Verification expired. Please register again.")
    form_data = parse_qs((await request.body()).decode("utf-8"))
    otp = form_data.get("otp", [""])[0].strip()
    username = str(pending["sub"])
    attempts = int(pending.get("attempts", 0))
    if attempts >= settings.otp_max_attempts:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many invalid codes. Please register again.")
    if not hmac.compare_digest(str(pending["digest"]), otp_digest(username, otp)):
        updated = dict(pending)
        updated["attempts"] = attempts + 1
        retry = RedirectResponse(url="/auth/verify-registration?error=invalid", status_code=status.HTTP_303_SEE_OTHER)
        retry.set_cookie("pending_registration", jwt.encode(updated, settings.secret_key, algorithm=settings.jwt_algorithm), httponly=True, samesite="lax", max_age=settings.otp_expire_minutes * 60, secure=False)
        return retry
    email = str(pending["email"])
    if db.scalar(select(User).where(or_(User.username == username, User.email == email))) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already registered")
    user = User(username=username, email=email, hashed_password=str(pending["password_hash"]), role=str(pending["role"]))
    db.add(user)
    db.commit()
    verified = RedirectResponse(url="/auth/login?registered=1", status_code=status.HTTP_303_SEE_OTHER)
    verified.delete_cookie("pending_registration")
    return verified


def _pending_login_token(username: str, email: str, otp: str) -> str:
    payload = {
        "type": "otp_pending",
        "sub": username,
        "email": email,
        "digest": otp_digest(username, otp),
        "attempts": 0,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def _decode_pending_login(token: str) -> dict[str, object] | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm], leeway=0)
    except jwt.InvalidTokenError:
        return None
    if payload.get("type") != "otp_pending":
        return None
    return payload


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

    if "text/html" in request.headers.get("accept", ""):
        otp = generate_otp()
        try:
            send_otp_email(user.email, otp)
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        redirect = RedirectResponse(url="/auth/verify-otp", status_code=status.HTTP_303_SEE_OTHER)
        redirect.set_cookie("pending_login", _pending_login_token(user.username, user.email, otp), httponly=True, samesite="lax", max_age=settings.otp_expire_minutes * 60, secure=False)
        return redirect

    log_activity(db, user, LOGIN, "user", user.id, f"{user.username} logged in")
    access_token = create_access_token(user.username)
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


@router.get("/verify-otp", response_class=HTMLResponse, include_in_schema=False)
def verify_otp_page(request: Request) -> Response:
    """Render the email OTP verification form."""

    if not request.cookies.get("pending_login"):
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "verify-otp.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description})


@router.post("/verify-otp", include_in_schema=False)
async def verify_otp(request: Request, response: Response, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    """Verify the email OTP and establish the authenticated browser session."""

    pending = _decode_pending_login(request.cookies.get("pending_login", ""))
    if pending is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Verification expired. Please log in again.")
    form_data = parse_qs((await request.body()).decode("utf-8"))
    otp = form_data.get("otp", [""])[0].strip()
    username = str(pending["sub"])
    attempts = int(pending.get("attempts", 0))
    if attempts >= settings.otp_max_attempts:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many invalid codes. Please log in again.")
    if not hmac.compare_digest(str(pending["digest"]), otp_digest(username, otp)):
        updated = dict(pending)
        updated["attempts"] = attempts + 1
        retry_token = jwt.encode(updated, settings.secret_key, algorithm=settings.jwt_algorithm)
        retry = RedirectResponse(url="/auth/verify-otp?error=invalid", status_code=status.HTTP_303_SEE_OTHER)
        retry.set_cookie("pending_login", retry_token, httponly=True, samesite="lax", max_age=settings.otp_expire_minutes * 60, secure=False)
        return retry
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or missing user")
    log_activity(db, user, LOGIN, "user", user.id, f"{user.username} logged in")
    access_token = create_access_token(user.username)
    verified = RedirectResponse(url="/auth/profile", status_code=status.HTTP_303_SEE_OTHER)
    verified.set_cookie("access_token", f"Bearer {access_token}", httponly=True, samesite="lax", max_age=settings.access_token_expire_minutes * 60, secure=False)
    verified.delete_cookie("pending_login")
    return verified


@router.get("/me", response_model=UserRead)
def read_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """Return the current authenticated user's profile details."""

    return current_user


@router.post("/logout")
def logout() -> RedirectResponse:
    """Clear the auth cookie and redirect to the login page."""

    response = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    response.delete_cookie("pending_login")
    return response


@router.get("/profile", response_class=HTMLResponse, include_in_schema=False)
def profile_page(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Render the current user's profile page or redirect anonymous visitors."""

    user = get_optional_current_user(request, db)
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(request,
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
    return templates.TemplateResponse(request,
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
    return templates.TemplateResponse(request,
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
