"""Shared SQLAlchemy declarative base for future models.

Phase 0 intentionally defines no database tables. Future model modules should
inherit from Base so Alembic can discover their metadata.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for future SQLAlchemy models."""
