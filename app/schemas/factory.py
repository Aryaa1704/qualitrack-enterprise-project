"""Pydantic schemas for factory management."""

from datetime import date, datetime

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
    """Data required to change a machine status."""

    status: str = Field(pattern="^(active|maintenance|inactive)$")


class MachineRead(MachineBase):
    """Machine details returned by the API."""

    id: int
    production_line_id: int
    factory_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MachineList(BaseModel):
    """Paginated machine list response."""

    items: list[MachineRead]
    page: int
    per_page: int
    total: int
    pages: int


class ProductBase(BaseModel):
    """Shared product fields."""

    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    sku_code: str = Field(min_length=1, max_length=50)
    status: str = Field(default="active", pattern="^(active|inactive)$")


class ProductCreate(ProductBase):
    """Data required to create a product."""


class ProductUpdate(BaseModel):
    """Data allowed when updating a product."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    sku_code: str | None = Field(default=None, min_length=1, max_length=50)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class ProductRead(ProductBase):
    """Product details returned by the API."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductList(BaseModel):
    """Paginated product list response."""

    items: list[ProductRead]
    page: int
    per_page: int
    total: int
    pages: int


class BatchBase(BaseModel):
    """Shared batch fields."""

    product_id: int
    production_line_id: int
    batch_number: str = Field(min_length=1, max_length=50)
    manufacturing_date: date
    expiry_date: date
    quantity: int = Field(gt=0)
    status: str = Field(default="planned", pattern="^(planned|in_progress|completed|expired|inactive)$")


class BatchCreate(BatchBase):
    """Data required to create a batch."""


class BatchUpdate(BaseModel):
    """Data allowed when updating a batch."""

    product_id: int | None = None
    production_line_id: int | None = None
    batch_number: str | None = Field(default=None, min_length=1, max_length=50)
    manufacturing_date: date | None = None
    expiry_date: date | None = None
    quantity: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, pattern="^(planned|in_progress|completed|expired|inactive)$")


class BatchRead(BatchBase):
    """Batch details returned by the API."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BatchList(BaseModel):
    """Paginated batch list response."""

    items: list[BatchRead]
    page: int
    per_page: int
    total: int
    pages: int


class InspectionBase(BaseModel):
    """Shared inspection fields submitted by inspectors."""

    batch_id: int
    scratch: str = Field(pattern="^(pass|fail)$")
    color: str = Field(pattern="^(pass|fail)$")
    weight_actual: float
    weight_spec: float
    dimensions_actual: str = Field(min_length=1, max_length=120)
    dimensions_spec: str = Field(min_length=1, max_length=120)
    packaging: str = Field(pattern="^(pass|fail)$")
    functional_test: str = Field(pattern="^(pass|fail)$")
    overall_status: str | None = Field(default=None, pattern="^(Pass|Fail)$")
    inspection_score: int = Field(ge=0, le=100)
    remarks: str = Field(default="", max_length=2000)


class InspectionCreate(InspectionBase):
    """Data required to create an inspection."""


class InspectionUpdate(BaseModel):
    """Data allowed when updating an inspection."""

    batch_id: int | None = None
    scratch: str | None = Field(default=None, pattern="^(pass|fail)$")
    color: str | None = Field(default=None, pattern="^(pass|fail)$")
    weight_actual: float | None = None
    weight_spec: float | None = None
    dimensions_actual: str | None = Field(default=None, min_length=1, max_length=120)
    dimensions_spec: str | None = Field(default=None, min_length=1, max_length=120)
    packaging: str | None = Field(default=None, pattern="^(pass|fail)$")
    functional_test: str | None = Field(default=None, pattern="^(pass|fail)$")
    overall_status: str | None = Field(default=None, pattern="^(Pass|Fail)$")
    inspection_score: int | None = Field(default=None, ge=0, le=100)
    remarks: str | None = Field(default=None, max_length=2000)


class InspectionRead(InspectionBase):
    """Inspection details returned by the API."""

    id: int
    inspector_id: int
    inspection_date: datetime

    model_config = ConfigDict(from_attributes=True)


class InspectionList(BaseModel):
    """Paginated inspection list response."""

    items: list[InspectionRead]
    page: int
    per_page: int
    total: int
    pages: int

DEFECT_TYPE_PATTERN = "^(Crack|Scratch|Missing Part|Paint Issue|Loose Component|Wrong Label|Custom)$"
DEFECT_SEVERITY_PATTERN = "^(Low|Medium|High)$"
DEFECT_STATUS_PATTERN = "^(Open|In Progress|Resolved)$"


class DefectBase(BaseModel):
    """Shared defect tracking fields."""

    inspection_id: int
    defect_type: str = Field(pattern=DEFECT_TYPE_PATTERN)
    severity: str = Field(pattern=DEFECT_SEVERITY_PATTERN)
    description: str = Field(min_length=1, max_length=2000)
    corrective_action: str = Field(default="", max_length=2000)
    status: str = Field(default="Open", pattern=DEFECT_STATUS_PATTERN)


class DefectCreate(DefectBase):
    """Data required to create a defect."""


class DefectUpdate(BaseModel):
    """Data allowed when updating a defect."""

    inspection_id: int | None = None
    defect_type: str | None = Field(default=None, pattern=DEFECT_TYPE_PATTERN)
    severity: str | None = Field(default=None, pattern=DEFECT_SEVERITY_PATTERN)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    corrective_action: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern=DEFECT_STATUS_PATTERN)


class DefectRead(DefectBase):
    """Defect details returned by the API."""

    id: int
    resolved_date: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DefectList(BaseModel):
    """Paginated defect list response."""

    items: list[DefectRead]
    page: int
    per_page: int
    total: int
    pages: int


class DefectStats(BaseModel):
    """Defect counts grouped for analytics consumers."""

    by_type: dict[str, int]
    by_severity: dict[str, int]
