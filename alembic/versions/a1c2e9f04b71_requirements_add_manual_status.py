"""requirements add manual_status

Revision ID: a1c2e9f04b71
Revises: 4471ed7a89ad
Create Date: 2026-08-17 12:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c2e9f04b71'
down_revision: Union[str, None] = '4471ed7a89ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 手动状态覆盖位：非空时 recalc 直接返回它，冻结需求状态（design.md 3.3）
    op.add_column("requirements", sa.Column("manual_status", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("requirements", schema=None) as batch_op:
        batch_op.drop_column("manual_status")
