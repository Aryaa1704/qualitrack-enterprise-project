"""create inspections table

Revision ID: 20260806_0006
Revises: 20260805_0005
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0006"
down_revision: str | None = "20260805_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create inspections table."""

    op.create_table(
        "inspections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("inspector_id", sa.Integer(), nullable=False),
        sa.Column("inspection_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scratch", sa.String(length=10), nullable=False),
        sa.Column("color", sa.String(length=10), nullable=False),
        sa.Column("weight_actual", sa.Float(), nullable=False),
        sa.Column("weight_spec", sa.Float(), nullable=False),
        sa.Column("dimensions_actual", sa.String(length=120), nullable=False),
        sa.Column("dimensions_spec", sa.String(length=120), nullable=False),
        sa.Column("packaging", sa.String(length=10), nullable=False),
        sa.Column("functional_test", sa.String(length=10), nullable=False),
        sa.Column("overall_status", sa.String(length=10), nullable=False),
        sa.Column("inspection_score", sa.Integer(), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
        sa.ForeignKeyConstraint(["inspector_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_inspections_batch_id"), "inspections", ["batch_id"], unique=False)
    op.create_index(op.f("ix_inspections_id"), "inspections", ["id"], unique=False)
    op.create_index(op.f("ix_inspections_inspector_id"), "inspections", ["inspector_id"], unique=False)


def downgrade() -> None:
    """Drop inspections table."""

    op.drop_index(op.f("ix_inspections_inspector_id"), table_name="inspections")
    op.drop_index(op.f("ix_inspections_id"), table_name="inspections")
    op.drop_index(op.f("ix_inspections_batch_id"), table_name="inspections")
    op.drop_table("inspections")
