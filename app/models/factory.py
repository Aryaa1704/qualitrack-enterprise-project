"""Factory hierarchy models for plant management."""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Factory(Base):
    """Top-level manufacturing site entity."""

    __tablename__ = "factories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    departments: Mapped[list["Department"]] = relationship(back_populates="factory")
    production_lines: Mapped[list["ProductionLine"]] = relationship(back_populates="factory")


class Department(Base):
    """Factory-scoped department grouping for production lines."""

    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("factory_id", "code", name="uq_departments_factory_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    factory: Mapped[Factory] = relationship(back_populates="departments")
    production_lines: Mapped[list["ProductionLine"]] = relationship(back_populates="department")


class ProductionLine(Base):
    """Factory-scoped production line optionally grouped by a department."""

    __tablename__ = "production_lines"
    __table_args__ = (UniqueConstraint("factory_id", "code", name="uq_production_lines_factory_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"), nullable=False, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    factory: Mapped[Factory] = relationship(back_populates="production_lines")
    department: Mapped[Department | None] = relationship(back_populates="production_lines")
    machines: Mapped[list["Machine"]] = relationship(back_populates="production_line")
    batches: Mapped[list["Batch"]] = relationship(back_populates="production_line")


class Machine(Base):
    """Production-line-scoped equipment used for manufacturing work."""

    __tablename__ = "machines"
    __table_args__ = (UniqueConstraint("production_line_id", "code", name="uq_machines_line_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    production_line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    production_line: Mapped[ProductionLine] = relationship(back_populates="machines")

    @property
    def factory_id(self) -> int:
        """Return the parent factory id through the production line."""

        return self.production_line.factory_id


class Product(Base):
    """Manufactured product catalog item."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    sku_code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    batches: Mapped[list["Batch"]] = relationship(back_populates="product")


class Batch(Base):
    """Production batch assigned to a product and production line."""

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    production_line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"), nullable=False, index=True)
    batch_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    manufacturing_date: Mapped[date] = mapped_column(Date(), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date(), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    product: Mapped[Product] = relationship(back_populates="batches")
    production_line: Mapped[ProductionLine] = relationship(back_populates="batches")
