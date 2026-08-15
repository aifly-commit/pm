"""change_logs old/new value nullable

Revision ID: 375ae54f5c05
Revises: 6cd6dae194fb
Create Date: 2026-08-14 23:01:19.488976

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '375ae54f5c05'
down_revision: Union[str, None] = '6cd6dae194fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 不支持直接 ALTER COLUMN，用 batch 模式重建表
    with op.batch_alter_table("stage_time_change_logs", schema=None) as batch_op:
        batch_op.alter_column("old_value", existing_type=sa.DateTime(), nullable=True)
        batch_op.alter_column("new_value", existing_type=sa.DateTime(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("stage_time_change_logs", schema=None) as batch_op:
        batch_op.alter_column("new_value", existing_type=sa.DateTime(), nullable=False)
        batch_op.alter_column("old_value", existing_type=sa.DateTime(), nullable=False)
