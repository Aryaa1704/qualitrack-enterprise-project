"""add production release search and filter indexes

Revision ID: 20260806_0009
Revises: 20260806_0008
Create Date: 2026-08-06 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260806_0009"
down_revision: str | None = "20260806_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add indexes for heavily searched, sorted, and filtered production fields."""

    op.create_index("ix_users_role", "users", ["role"], unique=False)
    op.create_index("ix_factories_name", "factories", ["name"], unique=False)
    op.create_index("ix_factories_location", "factories", ["location"], unique=False)
    op.create_index("ix_factories_status", "factories", ["status"], unique=False)
    op.create_index("ix_departments_name", "departments", ["name"], unique=False)
    op.create_index("ix_departments_status", "departments", ["status"], unique=False)
    op.create_index("ix_production_lines_name", "production_lines", ["name"], unique=False)
    op.create_index("ix_production_lines_status", "production_lines", ["status"], unique=False)
    op.create_index("ix_machines_name", "machines", ["name"], unique=False)
    op.create_index("ix_machines_type", "machines", ["type"], unique=False)
    op.create_index("ix_machines_status", "machines", ["status"], unique=False)
    op.create_index("ix_products_name", "products", ["name"], unique=False)
    op.create_index("ix_products_category", "products", ["category"], unique=False)
    op.create_index("ix_products_status", "products", ["status"], unique=False)
    op.create_index("ix_batches_manufacturing_date", "batches", ["manufacturing_date"], unique=False)
    op.create_index("ix_batches_status", "batches", ["status"], unique=False)
    op.create_index("ix_inspections_inspection_date", "inspections", ["inspection_date"], unique=False)
    op.create_index("ix_inspections_overall_status", "inspections", ["overall_status"], unique=False)
    op.create_index("ix_inspections_inspection_score", "inspections", ["inspection_score"], unique=False)
    op.create_index("ix_defects_created_at", "defects", ["created_at"], unique=False)


def downgrade() -> None:
    """Remove production release indexes."""

    op.drop_index("ix_defects_created_at", table_name="defects")
    op.drop_index("ix_inspections_inspection_score", table_name="inspections")
    op.drop_index("ix_inspections_overall_status", table_name="inspections")
    op.drop_index("ix_inspections_inspection_date", table_name="inspections")
    op.drop_index("ix_batches_status", table_name="batches")
    op.drop_index("ix_batches_manufacturing_date", table_name="batches")
    op.drop_index("ix_products_status", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_index("ix_machines_status", table_name="machines")
    op.drop_index("ix_machines_type", table_name="machines")
    op.drop_index("ix_machines_name", table_name="machines")
    op.drop_index("ix_production_lines_status", table_name="production_lines")
    op.drop_index("ix_production_lines_name", table_name="production_lines")
    op.drop_index("ix_departments_status", table_name="departments")
    op.drop_index("ix_departments_name", table_name="departments")
    op.drop_index("ix_factories_status", table_name="factories")
    op.drop_index("ix_factories_location", table_name="factories")
    op.drop_index("ix_factories_name", table_name="factories")
    op.drop_index("ix_users_role", table_name="users")
