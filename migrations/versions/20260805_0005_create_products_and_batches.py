"""create products and batches tables

Revision ID: 20260805_0005
Revises: 20260805_0004
Create Date: 2026-08-05 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0005"
down_revision: str | None = "20260805_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create products and batches tables."""

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("sku_code", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_products_id"), "products", ["id"], unique=False)
    op.create_index(op.f("ix_products_sku_code"), "products", ["sku_code"], unique=True)
    op.create_table(
        "batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("production_line_id", sa.Integer(), nullable=False),
        sa.Column("batch_number", sa.String(length=50), nullable=False),
        sa.Column("manufacturing_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["production_line_id"], ["production_lines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_batches_batch_number"), "batches", ["batch_number"], unique=True)
    op.create_index(op.f("ix_batches_id"), "batches", ["id"], unique=False)
    op.create_index(op.f("ix_batches_product_id"), "batches", ["product_id"], unique=False)
    op.create_index(op.f("ix_batches_production_line_id"), "batches", ["production_line_id"], unique=False)


def downgrade() -> None:
    """Drop products and batches tables."""

    op.drop_index(op.f("ix_batches_production_line_id"), table_name="batches")
    op.drop_index(op.f("ix_batches_product_id"), table_name="batches")
    op.drop_index(op.f("ix_batches_id"), table_name="batches")
    op.drop_index(op.f("ix_batches_batch_number"), table_name="batches")
    op.drop_table("batches")
    op.drop_index(op.f("ix_products_sku_code"), table_name="products")
    op.drop_index(op.f("ix_products_id"), table_name="products")
    op.drop_table("products")
