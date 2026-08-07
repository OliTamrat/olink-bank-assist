"""Add conversations.customer_name — address a customer by the name they gave.

Personal data, so it is only ever populated from an explicit self-introduction
and never written to logs. Nullable: most conversations never introduce a name.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("customer_name", sa.String(80), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "customer_name")
