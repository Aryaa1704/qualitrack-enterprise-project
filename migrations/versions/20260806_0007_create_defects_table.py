"""create defects table

Revision ID: 20260806_0007
Revises: 20260806_0006
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0007"
down_revision: str | None = "20260806_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create defects table."""

    op.create_table(
        "defects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inspection_id", sa.Integer(), nullable=False),
        sa.Column("defect_type", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("corrective_action", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resolved_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["inspection_id"], ["inspections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_defects_defect_type"), "defects", ["defect_type"], unique=False)
    op.create_index(op.f("ix_defects_id"), "defects", ["id"], unique=False)
    op.create_index(op.f("ix_defects_inspection_id"), "defects", ["inspection_id"], unique=False)
    op.create_index(op.f("ix_defects_severity"), "defects", ["severity"], unique=False)
    op.create_index(op.f("ix_defects_status"), "defects", ["status"], unique=False)


def downgrade() -> None:
    """Drop defects table."""

    op.drop_index(op.f("ix_defects_status"), table_name="defects")
    op.drop_index(op.f("ix_defects_severity"), table_name="defects")
    op.drop_index(op.f("ix_defects_inspection_id"), table_name="defects")
    op.drop_index(op.f("ix_defects_id"), table_name="defects")
    op.drop_index(op.f("ix_defects_defect_type"), table_name="defects")
    op.drop_table("defects")
