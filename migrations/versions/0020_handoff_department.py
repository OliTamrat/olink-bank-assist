"""Add handoffs.department and handoffs.priority.

Which desk an escalation belongs on, and whether it can wait. The queue
arrived as one undifferentiated list — every row carried a `reason`, but that
says why it LEFT the assistant, which is a process fact rather than a subject.
Forty rows reading "unanswered_question" is, from a desk, uncategorised.

Backfilled rather than left null. A migration that adds a filter and leaves
every existing row outside it produces a queue whose default view is empty on
the morning it ships, which reads as an outage. Every existing row lands in
`general` — the desk that exists precisely so nothing is orphaned — and an
operator can move any of them in one click. Backfilling them by re-running the
classifier over stored text would be a better guess and a much worse
migration: it would need the application's rules inside a schema change, and
those rules will have moved on by the time anybody runs this on a real
database.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "handoffs",
        sa.Column(
            "department", sa.String(length=32), nullable=False,
            server_default="general",
        ),
    )
    op.add_column(
        "handoffs",
        sa.Column(
            "priority", sa.String(length=16), nullable=False,
            server_default="normal",
        ),
    )
    # Indexed together because that is how the queue is read: one desk's work,
    # urgent first. A bank with three months of history and eight desks scans
    # the whole table for every page load without it.
    op.create_index(
        "ix_handoffs_desk", "handoffs", ["bank_id", "department", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_handoffs_desk", table_name="handoffs")
    op.drop_column("handoffs", "priority")
    op.drop_column("handoffs", "department")
