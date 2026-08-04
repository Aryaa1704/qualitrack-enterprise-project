"""Factory management routes."""

from math import ceil
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.models.factory import Factory
from app.models.user import User
from app.routers.auth import get_current_user, get_optional_current_user
from app.schemas.factory import FactoryCreate, FactoryList, FactoryRead, FactoryUpdate

router = APIRouter(prefix="/factories", tags=["Factories"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def _wants_html(request: Request) -> bool:
    """Return whether a request prefers an HTML response."""

    return "text/html" in request.headers.get("accept", "")


def _normalize_status(value: str | None) -> str:
    """Normalize factory status and reject unsupported values."""

    status_value = (value or "active").strip().lower()
    if status_value not in {"active", "inactive"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid factory status")
    return status_value


async def _factory_payload(request: Request, partial: bool = False) -> dict[str, str]:
    """Read JSON or URL-encoded factory fields from a request."""

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_payload = await request.json()
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid factory data")
        payload = {key: str(value).strip() for key, value in raw_payload.items() if value is not None}
    else:
        form_data = parse_qs((await request.body()).decode("utf-8"))
        payload = {key: values[0].strip() for key, values in form_data.items() if values}

    required_fields = {"name", "code", "location"}
    if not partial and not required_fields.issubset(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing factory data")

    for field in required_fields.intersection(payload):
        if not payload[field]:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid factory data")

    if "status" in payload or not partial:
        payload["status"] = _normalize_status(payload.get("status"))
    return payload


def _get_factory_or_404(db: Session, factory_id: int) -> Factory:
    """Return a factory by id or raise 404."""

    factory = db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Factory not found")
    return factory


def _ensure_unique_code(db: Session, code: str, factory_id: int | None = None) -> None:
    """Ensure a factory code is unique."""

    query = select(Factory).where(Factory.code == code)
    if factory_id is not None:
        query = query.where(Factory.id != factory_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Factory code already exists")


def _pagination(page: int, per_page: int) -> tuple[int, int]:
    """Normalize pagination inputs."""

    safe_page = max(page, 1)
    safe_per_page = min(max(per_page, 1), 50)
    return safe_page, safe_per_page


@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
def new_factory_page(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Render the factory creation form."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "factories/form.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": current_user,
            "factory": None,
            "form_action": "/factories",
            "form_title": "New Factory",
        },
    )


@router.post("", response_model=FactoryRead, status_code=status.HTTP_201_CREATED)
async def create_factory(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Factory | RedirectResponse:
    """Create a factory."""

    payload = await _factory_payload(request)
    factory_data = FactoryCreate(**payload)
    _ensure_unique_code(db, factory_data.code)
    factory = Factory(**factory_data.model_dump())
    db.add(factory)
    db.commit()
    db.refresh(factory)
    if _wants_html(request):
        return RedirectResponse(url=f"/factories/{factory.id}", status_code=status.HTTP_303_SEE_OTHER)
    return factory


@router.get("", response_model=FactoryList)
def list_factories(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    page: int = 1,
    per_page: int = 10,
) -> FactoryList | HTMLResponse:
    """List factories with pagination."""

    page, per_page = _pagination(page, per_page)
    total = db.scalar(select(func.count()).select_from(Factory)) or 0
    pages = max(ceil(total / per_page), 1)
    factories = list(
        db.scalars(select(Factory).order_by(Factory.id).offset((page - 1) * per_page).limit(per_page)).all()
    )
    if _wants_html(request):
        return templates.TemplateResponse(
            "factories/list.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "app_description": settings.app_description,
                "current_user": current_user,
                "factories": factories,
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": pages,
            },
        )
    return FactoryList(items=factories, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/{factory_id}", response_model=FactoryRead)
def get_factory(
    factory_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Factory | HTMLResponse:
    """Return factory details."""

    factory = _get_factory_or_404(db, factory_id)
    if _wants_html(request):
        return templates.TemplateResponse(
            "factories/detail.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "app_description": settings.app_description,
                "current_user": current_user,
                "factory": factory,
            },
        )
    return factory


@router.get("/{factory_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_factory_page(
    factory_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Render the factory edit form."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    factory = _get_factory_or_404(db, factory_id)
    return templates.TemplateResponse(
        "factories/form.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "current_user": current_user,
            "factory": factory,
            "form_action": f"/factories/{factory.id}/edit",
            "form_title": "Edit Factory",
        },
    )


@router.put("/{factory_id}", response_model=FactoryRead)
async def update_factory(
    factory_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Factory:
    """Update a factory."""

    factory = _get_factory_or_404(db, factory_id)
    payload = await _factory_payload(request, partial=True)
    factory_data = FactoryUpdate(**payload)
    updates = factory_data.model_dump(exclude_unset=True)
    if "code" in updates:
        _ensure_unique_code(db, updates["code"], factory_id=factory.id)
    for field, value in updates.items():
        setattr(factory, field, value)
    db.commit()
    db.refresh(factory)
    return factory


@router.post("/{factory_id}/edit", include_in_schema=False)
async def update_factory_from_form(
    factory_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Update a factory from the HTML form."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    factory = _get_factory_or_404(db, factory_id)
    payload = await _factory_payload(request)
    factory_data = FactoryUpdate(**payload)
    updates = factory_data.model_dump(exclude_unset=True)
    if "code" in updates:
        _ensure_unique_code(db, updates["code"], factory_id=factory.id)
    for field, value in updates.items():
        setattr(factory, field, value)
    db.commit()
    return RedirectResponse(url=f"/factories/{factory.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/{factory_id}", response_model=FactoryRead)
def delete_factory(
    factory_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Factory:
    """Soft-delete a factory by marking it inactive."""

    factory = _get_factory_or_404(db, factory_id)
    factory.status = "inactive"
    db.commit()
    db.refresh(factory)
    return factory


@router.post("/{factory_id}/delete", include_in_schema=False)
def delete_factory_from_form(
    factory_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Soft-delete a factory from the HTML detail page."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    factory = _get_factory_or_404(db, factory_id)
    factory.status = "inactive"
    db.commit()
    return RedirectResponse(url=f"/factories/{factory.id}", status_code=status.HTTP_303_SEE_OTHER)
