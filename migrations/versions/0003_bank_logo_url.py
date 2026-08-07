"""Add banks.logo_url — per-tenant logo for the widget header.

A brand colour alone left every tenant looking like the same product with a
different tint; the logo is what makes a bank recognise a demo as theirs.
Nullable, so existing tenants keep falling back to the name's initials.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("banks", sa.Column("logo_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("banks", "logo_url")
