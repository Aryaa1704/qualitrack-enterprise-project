"""Pydantic schemas for authentication and users."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    """Data required to create a user account."""

    username: str = Field(min_length=3, max_length=50)
    email: str
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    """Public user details returned by the API."""

    id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    """JWT access-token response."""

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Decoded token subject."""

    username: str | None = None



class UserRoleUpdate(BaseModel):
    """Role change payload for admin user management."""

    role: str = Field(pattern="^(admin|quality_manager|inspector)$")
