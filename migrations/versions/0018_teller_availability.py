"""Add banks.teller_enabled and users.teller_seen_at.

The two facts that together decide whether a customer is offered a live teller
at all:

- `banks.teller_enabled` — has this tenant bought and staffed the feature.
  Defaults FALSE, deliberately unlike `allow_general_knowledge` above it. Every
  existing tenant is mid-pilot with nobody sitting on a queue page, and a
  migration must not grow them a "Talk to a teller" button overnight.
- `users.teller_seen_at` — when this person was last watching the queue.
  Touched by the queue poll. Left NULL on backfill: nobody has ever polled,
  so nobody is online, which is the truth on the morning this ships.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "banks",
        sa.Column(
            "teller_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("teller_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "teller_seen_at")
    op.drop_column("banks", "teller_enabled")
