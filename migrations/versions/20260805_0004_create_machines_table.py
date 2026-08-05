"""create machines table

Revision ID: 20260805_0004
Revises: d0babbe87eec
Create Date: 2026-08-05 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0004"
down_revision: str | None = "d0babbe87eec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create machine assets assigned to production lines."""

    op.create_table(
        "machines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("factory_id", sa.Integer(), nullable=False),
        sa.Column("production_line_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("manufacturer", sa.String(length=120), nullable=True),
        sa.Column("model_number", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"]),
        sa.ForeignKeyConstraint(["production_line_id"], ["production_lines.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("factory_id", "code", name="uq_machines_factory_code"),
    )
    op.create_index(op.f("ix_machines_factory_id"), "machines", ["factory_id"], unique=False)
    op.create_index(op.f("ix_machines_id"), "machines", ["id"], unique=False)
    op.create_index(op.f("ix_machines_production_line_id"), "machines", ["production_line_id"], unique=False)


def downgrade() -> None:
    """Drop machine assets."""

    op.drop_index(op.f("ix_machines_production_line_id"), table_name="machines")
    op.drop_index(op.f("ix_machines_id"), table_name="machines")
    op.drop_index(op.f("ix_machines_factory_id"), table_name="machines")
    op.drop_table("machines")
