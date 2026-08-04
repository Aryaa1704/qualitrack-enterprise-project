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
