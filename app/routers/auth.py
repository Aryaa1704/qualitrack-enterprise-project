"""Authentication routes and dependencies."""

from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.templating import Jinja2Templates
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rbac import rbac_template_context
from app.database.session import get_db
from app.models.user import User
from app.schemas.user import Token, UserRead
from app.services.auth import create_access_token, decode_access_token, get_password_hash, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update(rbac_template_context())
settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


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

    user = User(username=username, email=email, hashed_password=get_password_hash(password))
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
