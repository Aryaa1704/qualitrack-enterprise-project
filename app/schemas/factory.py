"""Pydantic schemas for factory management."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FactoryBase(BaseModel):
    """Shared factory fields."""

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=50)
    location: str = Field(min_length=1, max_length=255)
    status: str = Field(default="active", pattern="^(active|inactive)$")


class FactoryCreate(FactoryBase):
    """Data required to create a factory."""


class FactoryUpdate(BaseModel):
    """Data allowed when updating a factory."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    location: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class FactoryRead(FactoryBase):
    """Factory details returned by the API."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FactoryList(BaseModel):
    """Paginated factory list response."""

    items: list[FactoryRead]
    page: int
    per_page: int
    total: int
    pages: int


class DepartmentBase(BaseModel):
    """Shared department fields."""

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=50)
    status: str = Field(default="active", pattern="^(active|inactive)$")


class DepartmentCreate(DepartmentBase):
    """Data required to create a department."""


class DepartmentUpdate(BaseModel):
    """Data allowed when updating a department."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class DepartmentRead(DepartmentBase):
    """Department details returned by the API."""

    id: int
    factory_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DepartmentList(BaseModel):
    """Paginated department list response."""

    items: list[DepartmentRead]
    page: int
    per_page: int
    total: int
    pages: int


class ProductionLineBase(BaseModel):
    """Shared production line fields."""

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=50)
    department_id: int | None = None
    status: str = Field(default="active", pattern="^(active|inactive)$")


class ProductionLineCreate(ProductionLineBase):
    """Data required to create a production line."""


class ProductionLineUpdate(BaseModel):
    """Data allowed when updating a production line."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    department_id: int | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class ProductionLineRead(ProductionLineBase):
    """Production line details returned by the API."""

    id: int
    factory_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductionLineList(BaseModel):
    """Paginated production line list response."""

    items: list[ProductionLineRead]
    page: int
    per_page: int
    total: int
    pages: int


class MachineBase(BaseModel):
    """Shared machine fields."""

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=50)
    type: str = Field(min_length=1, max_length=80)
    status: str = Field(default="active", pattern="^(active|maintenance|inactive)$")


class MachineCreate(MachineBase):
    """Data required to create a machine."""


class MachineUpdate(BaseModel):
    """Data allowed when updating a machine."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    type: str | None = Field(default=None, min_length=1, max_length=80)
    status: str | None = Field(default=None, pattern="^(active|maintenance|inactive)$")


class MachineStatusUpdate(BaseModel):
    """Data required to change machine status."""

    status: str = Field(pattern="^(active|maintenance|inactive)$")


class MachineRead(MachineBase):
    """Machine details returned by the API."""

    id: int
    production_line_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MachineList(BaseModel):
    """Paginated machine list response."""

    items: list[MachineRead]
    page: int
    per_page: int
    total: int
    pages: int
