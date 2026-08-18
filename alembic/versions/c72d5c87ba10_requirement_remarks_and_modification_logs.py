"""add requirement remarks and modification logs

Revision ID: c72d5c87ba10
Revises: a1c2e9f04b71
Create Date: 2026-08-18 15:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c72d5c87ba10"
down_revision: Union[str, None] = "a1c2e9f04b71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("requirements", sa.Column("remark", sa.Text(), nullable=True))
    op.create_table(
        "requirement_modification_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_requirement_modification_logs_requirement_created",
        "requirement_modification_logs",
        ["requirement_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_requirement_modification_logs_requirement_created",
        table_name="requirement_modification_logs",
    )
    op.drop_table("requirement_modification_logs")
    with op.batch_alter_table("requirements", schema=None) as batch_op:
        batch_op.drop_column("remark")
