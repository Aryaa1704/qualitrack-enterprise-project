"""Product management routes."""

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
from app.models.factory import Batch, Product
from app.models.user import User
from app.routers.auth import ADMIN, QUALITY_MANAGER, get_current_user, get_optional_current_user, redirect_if_forbidden, require_role
from app.schemas.factory import ProductCreate, ProductList, ProductRead, ProductUpdate

router = APIRouter(prefix="/products", tags=["Products"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _pagination(page: int, per_page: int, page_size: int | None = None) -> tuple[int, int]:
    effective_size = page_size if page_size is not None else per_page
    return max(page, 1), min(max(effective_size, 1), 50)


def _normalize_status(value: str | None) -> str:
    status_value = (value or "active").strip().lower()
    if status_value not in {"active", "inactive"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid product status")
    return status_value


async def _product_payload(request: Request, partial: bool = False) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_payload = await request.json()
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid product data")
        payload = {key: str(value).strip() for key, value in raw_payload.items() if value is not None}
    else:
        form_data = parse_qs((await request.body()).decode("utf-8"))
        payload = {key: values[0].strip() for key, values in form_data.items() if values}
    required_fields = {"name", "category", "sku_code"}
    if not partial and not required_fields.issubset(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing product data")
    for field in required_fields.intersection(payload):
        if not payload[field]:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid product data")
    if "status" in payload or not partial:
        payload["status"] = _normalize_status(payload.get("status"))
    return payload


def _get_product_or_404(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


def _ensure_unique_sku(db: Session, sku_code: str, product_id: int | None = None) -> None:
    query = select(Product).where(Product.sku_code == sku_code)
    if product_id is not None:
        query = query.where(Product.id != product_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product SKU already exists")


@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
def new_product_page(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
    return templates.TemplateResponse("products/form.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "product": None, "form_action": "/products", "form_title": "New Product"})


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN))]) -> Product | RedirectResponse:
    payload = await _product_payload(request)
    product_data = ProductCreate(**payload)
    _ensure_unique_sku(db, product_data.sku_code)
    product = Product(**product_data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    if _wants_html(request):
        return RedirectResponse(url=f"/products/{product.id}", status_code=status.HTTP_303_SEE_OTHER)
    return product


@router.get("", response_model=ProductList)
def list_products(request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))], search: str | None = None, category: str | None = None, status_filter: str | None = None, sort_by: str = "id", sort_order: str = "asc", page: int = 1, page_size: int | None = None, per_page: int = 10) -> ProductList | HTMLResponse:
    page, per_page = _pagination(page, per_page, page_size)
    query = select(Product)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Product.name.ilike(term), Product.sku_code.ilike(term), Product.category.ilike(term)))
    if category:
        query = query.where(Product.category == category.strip())
    if status_filter:
        query = query.where(Product.status == _normalize_status(status_filter))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(ceil(total / per_page), 1)
    sort_columns = {"id": Product.id, "name": Product.name, "category": Product.category, "sku_code": Product.sku_code, "status": Product.status, "created_at": Product.created_at}
    sort_column = sort_columns.get(sort_by, Product.id)
    direction = sort_order.lower()
    order_by = sort_column.desc() if direction == "desc" else sort_column.asc()
    products = list(db.scalars(query.order_by(order_by, Product.id).offset((page - 1) * per_page).limit(per_page)).all())
    if _wants_html(request):
        categories = list(db.scalars(select(Product.category).distinct().order_by(Product.category)).all())
        return templates.TemplateResponse("products/list.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "products": products, "categories": categories, "search": search or "", "category": category or "", "status_filter": status_filter or "", "page": page, "per_page": per_page, "total": total, "pages": pages, "sort_by": sort_by, "sort_order": direction, "page_size": per_page})
    return ProductList(items=products, page=page, per_page=per_page, total=total, pages=pages)


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN, QUALITY_MANAGER))]) -> Product | HTMLResponse:
    product = _get_product_or_404(db, product_id)
    if _wants_html(request):
        batches = list(db.scalars(select(Batch).where(Batch.product_id == product.id).order_by(Batch.manufacturing_date.desc(), Batch.id.desc())).all())
        return templates.TemplateResponse("products/detail.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "product": product, "batches": batches})
    return product


@router.get("/{product_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_product_page(product_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
    product = _get_product_or_404(db, product_id)
    return templates.TemplateResponse("products/form.html", {"request": request, "app_name": settings.app_name, "app_description": settings.app_description, "current_user": current_user, "product": product, "form_action": f"/products/{product.id}/edit", "form_title": "Edit Product"})


@router.put("/{product_id}", response_model=ProductRead)
async def update_product(product_id: int, request: Request, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN))]) -> Product:
    product = _get_product_or_404(db, product_id)
    updates = ProductUpdate(**await _product_payload(request, partial=True)).model_dump(exclude_unset=True)
    if "sku_code" in updates:
        _ensure_unique_sku(db, updates["sku_code"], product.id)
    for field, value in updates.items():
        setattr(product, field, value)
    db.commit(); db.refresh(product)
    return product


@router.post("/{product_id}/edit", include_in_schema=False)
async def update_product_from_form(product_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    await update_product(product_id, request, db, current_user)
    return RedirectResponse(url=f"/products/{product_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/{product_id}", response_model=ProductRead)
def delete_product(product_id: int, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_role(ADMIN))]) -> Product:
    product = _get_product_or_404(db, product_id)
    product.status = "inactive"
    db.commit(); db.refresh(product)
    return product


@router.post("/{product_id}/delete", include_in_schema=False)
def delete_product_from_form(product_id: int, request: Request, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    current_user = get_optional_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    forbidden = redirect_if_forbidden(current_user, ADMIN)
    if forbidden is not None:
        return forbidden
    product = _get_product_or_404(db, product_id)
    product.status = "inactive"
    db.commit()
    return RedirectResponse(url=f"/products/{product_id}", status_code=status.HTTP_303_SEE_OTHER)
