"""Factory management routes."""

from math import ceil
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.models.factory import Department, Factory, Machine, ProductionLine
from app.models.user import User
from app.routers.auth import ADMIN, QUALITY_MANAGER, get_current_user, get_optional_current_user, redirect_if_forbidden, require_role
from app.schemas.factory import (
    DepartmentCreate,
    DepartmentList,
    DepartmentRead,
    DepartmentUpdate,
    FactoryCreate,
    FactoryList,
    FactoryRead,
    FactoryUpdate,
    MachineCreate,
    MachineList,
    MachineRead,
    MachineStatusUpdate,
    MachineUpdate,
    ProductionLineCreate,
    ProductionLineList,
    ProductionLineRead,
    ProductionLineUpdate,
)

router = APIRouter(prefix="/factories", tags=["Factories"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def _wants_html(request: Request) -> bool:
    """Return whether a request prefers an HTML response."""

    return "text/html" in request.headers.get("accept", "")


def _normalize_status(value: str | None, entity: str = "factory") -> str:
    """Normalize status and reject unsupported values."""

    allowed_statuses = {"active", "maintenance", "inactive"} if entity == "machine" else {"active", "inactive"}
    status_value = (value or "active").strip().lower()
    if status_value not in allowed_statuses:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {entity} status")
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


async def _hierarchy_payload(request: Request, required_fields: set[str], entity: str, partial: bool = False) -> dict[str, str | int | None]:
    """Read JSON or URL-encoded department/line fields from a request."""

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_payload = await request.json()
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {entity} data")
        payload: dict[str, str | int | None] = {key: value for key, value in raw_payload.items()}
    else:
        form_data = parse_qs((await request.body()).decode("utf-8"))
        payload = {key: values[0].strip() for key, values in form_data.items() if values}

    if not partial and not required_fields.issubset(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Missing {entity} data")

    for field in required_fields.intersection(payload):
        value = payload[field]
        if value is None or not str(value).strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {entity} data")
        payload[field] = str(value).strip()

    for field in {"name", "code"}.intersection(payload):
        if payload[field] is not None:
            payload[field] = str(payload[field]).strip()

    if "department_id" in payload:
        department_value = payload["department_id"]
        payload["department_id"] = int(department_value) if department_value is not None and str(department_value).strip() else None

    if "status" in payload or not partial:
        payload["status"] = _normalize_status(str(payload.get("status") or "active"), entity)
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


def _ensure_department_code_unique(db: Session, factory_id: int, code: str, dept_id: int | None = None) -> None:
    """Ensure a department code is unique within a factory."""

    query = select(Department).where(Department.factory_id == factory_id, Department.code == code)
    if dept_id is not None:
        query = query.where(Department.id != dept_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Department code already exists")


def _ensure_line_code_unique(db: Session, factory_id: int, code: str, line_id: int | None = None) -> None:
    """Ensure a production line code is unique within a factory."""

    query = select(ProductionLine).where(ProductionLine.factory_id == factory_id, ProductionLine.code == code)
    if line_id is not None:
        query = query.where(ProductionLine.id != line_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Production line code already exists")


def _get_department_or_404(db: Session, factory_id: int, dept_id: int) -> Department:
    """Return an active department under a factory or raise 404."""

    department = db.scalar(
        select(Department).where(
            Department.id == dept_id,
            Department.factory_id == factory_id,
            Department.status == "active",
        )
    )
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    return department


def _get_line_or_404(db: Session, factory_id: int, line_id: int) -> ProductionLine:
    """Return an active production line under a factory or raise 404."""

    production_line = db.scalar(
        select(ProductionLine).where(
            ProductionLine.id == line_id,
            ProductionLine.factory_id == factory_id,
            ProductionLine.status == "active",
        )
    )
    if production_line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Production line not found")
    return production_line


def _ensure_machine_code_unique(db: Session, line_id: int, code: str, machine_id: int | None = None) -> None:
    """Ensure a machine code is unique within a production line."""

    query = select(Machine).where(Machine.production_line_id == line_id, Machine.code == code)
    if machine_id is not None:
        query = query.where(Machine.id != machine_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Machine code already exists")


def _get_machine_or_404(db: Session, line_id: int, machine_id: int) -> Machine:
    """Return a machine under a production line or raise 404."""

    machine = db.scalar(select(Machine).where(Machine.id == machine_id, Machine.production_line_id == line_id))
    if machine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    return machine

def _ensure_department_belongs_to_factory(db: Session, factory_id: int, department_id: int | None) -> None:
    """Validate an optional department belongs to the target factory."""

    if department_id is None:
        return
    _get_department_or_404(db, factory_id, department_id)


def _pagination(page: int, per_page: int, page_size: int | None = None) -> tuple[int, int]:
    """Normalize pagination inputs."""

    effective_size = page_size if page_size is not None else per_page
    safe_page = max(page, 1)
    safe_per_page = min(max(effective_size, 1), 50)
    return safe_page, safe_per_page


@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
def new_factory_page(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Render the factory creation form."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
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
    current_user: Annotated[User, Depends(require_role(ADMIN))],
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
    current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))],
    page: int = 1,
    per_page: int = 10,
    page_size: int | None = None,
    search: str | None = None,
    sort_by: str = "id",
    sort_order: str = "asc",
) -> FactoryList | HTMLResponse:
    """List factories with search, sorting, and pagination."""

    page, per_page = _pagination(page, per_page, page_size)
    query = select(Factory)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Factory.name.ilike(term), Factory.code.ilike(term), Factory.location.ilike(term), Factory.status.ilike(term)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(ceil(total / per_page), 1)
    factories = list(
        db.scalars(query.order_by(({"id": Factory.id, "name": Factory.name, "code": Factory.code, "location": Factory.location, "status": Factory.status, "created_at": Factory.created_at}.get(sort_by, Factory.id).desc() if sort_order.lower() == "desc" else {"id": Factory.id, "name": Factory.name, "code": Factory.code, "location": Factory.location, "status": Factory.status, "created_at": Factory.created_at}.get(sort_by, Factory.id).asc()), Factory.id).offset((page - 1) * per_page).limit(per_page)).all()
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
                "search": search or "",
                "sort_by": sort_by,
                "sort_order": sort_order.lower(),
                "page_size": per_page,
            },
        )
    return FactoryList(items=factories, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/{factory_id}", response_model=FactoryRead)
def get_factory(
    factory_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))],
) -> Factory | HTMLResponse:
    """Return factory details."""

    factory = _get_factory_or_404(db, factory_id)
    if _wants_html(request):
        departments = list(
            db.scalars(
                select(Department)
                .where(Department.factory_id == factory.id, Department.status == "active")
                .order_by(Department.id)
                .limit(10)
            ).all()
        )
        production_lines = list(
            db.scalars(
                select(ProductionLine)
                .where(ProductionLine.factory_id == factory.id, ProductionLine.status == "active")
                .order_by(ProductionLine.id)
                .limit(10)
            ).all()
        )
        return templates.TemplateResponse(
            "factories/detail.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "app_description": settings.app_description,
                "current_user": current_user,
                "factory": factory,
                "departments": departments,
                "production_lines": production_lines,
                "machines": list(
                    db.scalars(
                        select(Machine)
                        .join(ProductionLine)
                        .where(ProductionLine.factory_id == factory.id)
                        .order_by(Machine.id)
                        .limit(25)
                    ).all()
                ),
                "machine_status_filter": "",
                "machine_line_filter": "",
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
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
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
    current_user: Annotated[User, Depends(require_role(ADMIN))],
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
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
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
    current_user: Annotated[User, Depends(require_role(ADMIN))],
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
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
    factory = _get_factory_or_404(db, factory_id)
    factory.status = "inactive"
    db.commit()
    return RedirectResponse(url=f"/factories/{factory.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{factory_id}/departments", response_model=DepartmentRead, status_code=status.HTTP_201_CREATED)
async def create_department(
    factory_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> Department | RedirectResponse:
    """Create a department under a factory."""

    _get_factory_or_404(db, factory_id)
    payload = await _hierarchy_payload(request, {"name", "code"}, "department")
    department_data = DepartmentCreate(**payload)
    _ensure_department_code_unique(db, factory_id, department_data.code)
    department = Department(factory_id=factory_id, **department_data.model_dump())
    db.add(department)
    db.commit()
    db.refresh(department)
    if _wants_html(request):
        return RedirectResponse(url=f"/factories/{factory_id}#departments", status_code=status.HTTP_303_SEE_OTHER)
    return department


@router.get("/{factory_id}/departments", response_model=DepartmentList)
def list_departments(
    factory_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))],
    page: int = 1,
    per_page: int = 10,
) -> DepartmentList:
    """List active departments under a factory with pagination."""

    _get_factory_or_404(db, factory_id)
    page, per_page = _pagination(page, per_page)
    base = select(Department).where(Department.factory_id == factory_id, Department.status == "active")
    total = db.scalar(select(func.count()).select_from(Department).where(Department.factory_id == factory_id, Department.status == "active")) or 0
    pages = max(ceil(total / per_page), 1)
    items = list(db.scalars(base.order_by(Department.id).offset((page - 1) * per_page).limit(per_page)).all())
    return DepartmentList(items=items, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/{factory_id}/departments/{dept_id}", response_model=DepartmentRead)
def get_department(
    factory_id: int,
    dept_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))],
) -> Department:
    """Return one active department under a factory."""

    _get_factory_or_404(db, factory_id)
    return _get_department_or_404(db, factory_id, dept_id)


@router.put("/{factory_id}/departments/{dept_id}", response_model=DepartmentRead)
async def update_department(
    factory_id: int,
    dept_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> Department:
    """Update an active department."""

    _get_factory_or_404(db, factory_id)
    department = _get_department_or_404(db, factory_id, dept_id)
    payload = await _hierarchy_payload(request, {"name", "code"}, "department", partial=True)
    updates = DepartmentUpdate(**payload).model_dump(exclude_unset=True)
    if "code" in updates:
        _ensure_department_code_unique(db, factory_id, updates["code"], dept_id=department.id)
    for field, value in updates.items():
        setattr(department, field, value)
    db.commit()
    db.refresh(department)
    return department


@router.delete("/{factory_id}/departments/{dept_id}", response_model=DepartmentRead)
def delete_department(
    factory_id: int,
    dept_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> Department:
    """Soft-delete a department by marking it inactive."""

    _get_factory_or_404(db, factory_id)
    department = _get_department_or_404(db, factory_id, dept_id)
    department.status = "inactive"
    db.commit()
    db.refresh(department)
    return department


@router.post("/{factory_id}/departments/{dept_id}/delete", include_in_schema=False)
def delete_department_from_form(
    factory_id: int,
    dept_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Soft-delete a department from the HTML detail page."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    department = _get_department_or_404(db, factory_id, dept_id)
    department.status = "inactive"
    db.commit()
    return RedirectResponse(url=f"/factories/{factory_id}#departments", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{factory_id}/production-lines", response_model=ProductionLineRead, status_code=status.HTTP_201_CREATED)
async def create_production_line(
    factory_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> ProductionLine | RedirectResponse:
    """Create a production line under a factory."""

    _get_factory_or_404(db, factory_id)
    payload = await _hierarchy_payload(request, {"name", "code"}, "production line")
    line_data = ProductionLineCreate(**payload)
    _ensure_department_belongs_to_factory(db, factory_id, line_data.department_id)
    _ensure_line_code_unique(db, factory_id, line_data.code)
    production_line = ProductionLine(factory_id=factory_id, **line_data.model_dump())
    db.add(production_line)
    db.commit()
    db.refresh(production_line)
    if _wants_html(request):
        return RedirectResponse(url=f"/factories/{factory_id}#production-lines", status_code=status.HTTP_303_SEE_OTHER)
    return production_line


@router.get("/{factory_id}/production-lines", response_model=ProductionLineList)
def list_production_lines(
    factory_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))],
    page: int = 1,
    per_page: int = 10,
) -> ProductionLineList:
    """List active production lines under a factory with pagination."""

    _get_factory_or_404(db, factory_id)
    page, per_page = _pagination(page, per_page)
    total = db.scalar(select(func.count()).select_from(ProductionLine).where(ProductionLine.factory_id == factory_id, ProductionLine.status == "active")) or 0
    pages = max(ceil(total / per_page), 1)
    items = list(
        db.scalars(
            select(ProductionLine)
            .where(ProductionLine.factory_id == factory_id, ProductionLine.status == "active")
            .order_by(ProductionLine.id)
            .offset((page - 1) * per_page)
            .limit(per_page)
        ).all()
    )
    return ProductionLineList(items=items, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/{factory_id}/production-lines/{line_id}", response_model=ProductionLineRead)
def get_production_line(
    factory_id: int,
    line_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))],
) -> ProductionLine:
    """Return one active production line under a factory."""

    _get_factory_or_404(db, factory_id)
    return _get_line_or_404(db, factory_id, line_id)


@router.put("/{factory_id}/production-lines/{line_id}", response_model=ProductionLineRead)
async def update_production_line(
    factory_id: int,
    line_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> ProductionLine:
    """Update an active production line."""

    _get_factory_or_404(db, factory_id)
    production_line = _get_line_or_404(db, factory_id, line_id)
    payload = await _hierarchy_payload(request, {"name", "code"}, "production line", partial=True)
    updates = ProductionLineUpdate(**payload).model_dump(exclude_unset=True)
    if "department_id" in updates:
        _ensure_department_belongs_to_factory(db, factory_id, updates["department_id"])
    if "code" in updates:
        _ensure_line_code_unique(db, factory_id, updates["code"], line_id=production_line.id)
    for field, value in updates.items():
        setattr(production_line, field, value)
    db.commit()
    db.refresh(production_line)
    return production_line


@router.delete("/{factory_id}/production-lines/{line_id}", response_model=ProductionLineRead)
def delete_production_line(
    factory_id: int,
    line_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> ProductionLine:
    """Soft-delete a production line by marking it inactive."""

    _get_factory_or_404(db, factory_id)
    production_line = _get_line_or_404(db, factory_id, line_id)
    production_line.status = "inactive"
    db.commit()
    db.refresh(production_line)
    return production_line


@router.post("/{factory_id}/production-lines/{line_id}/delete", include_in_schema=False)
def delete_production_line_from_form(
    factory_id: int,
    line_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Soft-delete a production line from the HTML detail page."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    production_line = _get_line_or_404(db, factory_id, line_id)
    production_line.status = "inactive"
    db.commit()
    return RedirectResponse(url=f"/factories/{factory_id}#production-lines", status_code=status.HTTP_303_SEE_OTHER)



@router.post("/{factory_id}/machines", include_in_schema=False)
async def create_machine_from_factory_form(
    factory_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Create a machine from the factory detail page."""

    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    payload = await _hierarchy_payload(request, {"production_line_id", "name", "code", "type"}, "machine")
    line_id = int(payload.pop("production_line_id"))
    _get_factory_or_404(db, factory_id)
    _get_line_or_404(db, factory_id, line_id)
    machine_data = MachineCreate(**payload)
    _ensure_machine_code_unique(db, line_id, machine_data.code)
    machine = Machine(production_line_id=line_id, **machine_data.model_dump())
    db.add(machine)
    db.commit()
    return RedirectResponse(url=f"/factories/{factory_id}#machines", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{factory_id}/production-lines/{line_id}/machines", response_model=MachineRead, status_code=status.HTTP_201_CREATED)
async def create_machine(
    factory_id: int,
    line_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> Machine | RedirectResponse:
    """Create a machine under a production line."""

    _get_factory_or_404(db, factory_id)
    _get_line_or_404(db, factory_id, line_id)
    payload = await _hierarchy_payload(request, {"name", "code", "type"}, "machine")
    machine_data = MachineCreate(**payload)
    _ensure_machine_code_unique(db, line_id, machine_data.code)
    machine = Machine(production_line_id=line_id, **machine_data.model_dump())
    db.add(machine)
    db.commit()
    db.refresh(machine)
    if _wants_html(request):
        return RedirectResponse(url=f"/factories/{factory_id}#machines", status_code=status.HTTP_303_SEE_OTHER)
    return machine


@router.get("/{factory_id}/production-lines/{line_id}/machines", response_model=MachineList)
def list_machines(
    factory_id: int,
    line_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))],
    status: str | None = None,
    status_filter: str | None = None,
    production_line_id: int | None = None,
    factory_filter_id: int | None = None,
    page: int = 1,
    per_page: int = 10,
) -> MachineList:
    """List machines with status, production line, and factory filters."""

    _get_factory_or_404(db, factory_id)
    _get_line_or_404(db, factory_id, line_id)
    page, per_page = _pagination(page, per_page)
    query = select(Machine).join(ProductionLine).where(ProductionLine.factory_id == factory_id)
    if production_line_id is not None:
        query = query.where(Machine.production_line_id == production_line_id)
    else:
        query = query.where(Machine.production_line_id == line_id)
    if factory_filter_id is not None:
        query = query.where(ProductionLine.factory_id == factory_filter_id)
    requested_status = status_filter or status
    if requested_status:
        query = query.where(Machine.status == _normalize_status(requested_status, "machine"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(ceil(total / per_page), 1)
    items = list(db.scalars(query.order_by(Machine.id).offset((page - 1) * per_page).limit(per_page)).all())
    return MachineList(items=items, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/{factory_id}/production-lines/{line_id}/machines/{machine_id}", response_model=MachineRead)
def get_machine(
    factory_id: int,
    line_id: int,
    machine_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))],
) -> Machine:
    """Return one machine under a production line."""

    _get_factory_or_404(db, factory_id)
    _get_line_or_404(db, factory_id, line_id)
    return _get_machine_or_404(db, line_id, machine_id)


@router.put("/{factory_id}/production-lines/{line_id}/machines/{machine_id}", response_model=MachineRead)
async def update_machine(
    factory_id: int,
    line_id: int,
    machine_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> Machine:
    """Update a machine."""

    _get_factory_or_404(db, factory_id)
    _get_line_or_404(db, factory_id, line_id)
    machine = _get_machine_or_404(db, line_id, machine_id)
    payload = await _hierarchy_payload(request, {"name", "code", "type"}, "machine", partial=True)
    updates = MachineUpdate(**payload).model_dump(exclude_unset=True)
    if "code" in updates:
        _ensure_machine_code_unique(db, line_id, updates["code"], machine_id=machine.id)
    for field, value in updates.items():
        setattr(machine, field, value)
    db.commit()
    db.refresh(machine)
    return machine


@router.patch("/{factory_id}/production-lines/{line_id}/machines/{machine_id}/status", response_model=MachineRead)
@router.post("/{factory_id}/production-lines/{line_id}/machines/{machine_id}/status", response_model=MachineRead, include_in_schema=False)
async def change_machine_status(
    factory_id: int,
    line_id: int,
    machine_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> Machine | RedirectResponse:
    """Change only a machine status."""

    _get_factory_or_404(db, factory_id)
    _get_line_or_404(db, factory_id, line_id)
    machine = _get_machine_or_404(db, line_id, machine_id)
    payload = await _hierarchy_payload(request, {"status"}, "machine")
    status_data = MachineStatusUpdate(**payload)
    machine.status = status_data.status
    db.commit()
    db.refresh(machine)
    if _wants_html(request):
        return RedirectResponse(url=f"/factories/{factory_id}#machines", status_code=status.HTTP_303_SEE_OTHER)
    return machine


@router.delete("/{factory_id}/production-lines/{line_id}/machines/{machine_id}", response_model=MachineRead)
def delete_machine(
    factory_id: int,
    line_id: int,
    machine_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(ADMIN))],
) -> Machine:
    """Soft-delete a machine by marking it inactive."""

    _get_factory_or_404(db, factory_id)
    _get_line_or_404(db, factory_id, line_id)
    machine = _get_machine_or_404(db, line_id, machine_id)
    machine.status = "inactive"
    db.commit()
    db.refresh(machine)
    return machine
