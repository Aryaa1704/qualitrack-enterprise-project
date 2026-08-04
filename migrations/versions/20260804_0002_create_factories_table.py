"""create factories table

Revision ID: 20260804_0002
Revises: 20260803_0001
Create Date: 2026-08-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0002"
down_revision: str | None = "20260803_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the factories table."""

    op.create_table(
        "factories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_factories_code"), "factories", ["code"], unique=True)
    op.create_index(op.f("ix_factories_id"), "factories", ["id"], unique=False)


def downgrade() -> None:
    """Drop the factories table."""

    op.drop_index(op.f("ix_factories_id"), table_name="factories")
    op.drop_index(op.f("ix_factories_code"), table_name="factories")
    op.drop_table("factories")
