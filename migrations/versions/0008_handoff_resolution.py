"""Record how a handoff was resolved, not just that it was.

The queue could only move a row from open to closed. That is enough to make it
disappear and not enough to run a support function: nobody can tell whether a
customer was called back, whether the answer got written into the knowledge
base, or whether someone closed it to clear the list.

`resolution` is free text on purpose. A fixed set of codes would have to be
guessed now, before a single bank has worked the queue, and the wrong
vocabulary is harder to remove later than no vocabulary.

There is no `resolved_by`. Admin tokens are per-tenant, not per-person, so any
name recorded here would be a guess dressed up as an audit trail. That needs
real operator accounts, which is Phase 3 work.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("handoffs", sa.Column("resolution", sa.Text(), nullable=True))
    op.add_column(
        "handoffs",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The queue is worked open-first, oldest-first. Without this the console's
    # default view is a filtered sort over every handoff the tenant has ever
    # filed.
    op.create_index(
        "ix_handoffs_bank_status_created",
        "handoffs",
        ["bank_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_handoffs_bank_status_created", table_name="handoffs")
    op.drop_column("handoffs", "resolved_at")
    op.drop_column("handoffs", "resolution")
