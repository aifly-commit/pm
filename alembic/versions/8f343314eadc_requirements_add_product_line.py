"""requirements add product_line

Revision ID: 8f343314eadc
Revises: d71563e372e1
Create Date: 2026-08-16 14:09:08.166014

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8f343314eadc'
down_revision: Union[str, None] = 'd71563e372e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("requirements", sa.Column("product_line", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("requirements", schema=None) as batch_op:
        batch_op.drop_column("product_line")
