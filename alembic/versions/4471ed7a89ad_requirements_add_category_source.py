"""requirements add category source

Revision ID: 4471ed7a89ad
Revises: 8f343314eadc
Create Date: 2026-08-16 15:38:33.240317

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4471ed7a89ad'
down_revision: Union[str, None] = '8f343314eadc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("requirements", sa.Column("category", sa.String(length=16), nullable=True))
    op.add_column("requirements", sa.Column("source", sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("requirements", schema=None) as batch_op:
        batch_op.drop_column("source")
        batch_op.drop_column("category")
