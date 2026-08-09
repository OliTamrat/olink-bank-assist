"""Add users.teller_languages.

Which languages a teller can actually hold a conversation in, so a waiting
customer is offered first to somebody who can talk to them.

Nullable with no backfill, deliberately. NULL and [] both mean "not declared",
which the routing treats as "can take anything" — every existing teller is
undeclared on the morning this ships, and a stricter reading would empty every
queue at once and look like an outage rather than a feature.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("teller_languages", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "teller_languages")
