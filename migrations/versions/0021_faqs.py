"""Add the faqs table.

Answers a bank has written and approved, served verbatim with no model call.
The same twenty questions are most of a bank's traffic; today each one costs a
retrieval and a Gemini call for an answer that has not changed since the last
person asked it.

The unique constraint on (bank_id, lookup) is the load-bearing part. Without
it the same question can be published twice — two different answers, and which
one a customer reads comes down to row order. A database error at publish time
is a message an operator can act on; two answers in production is a support
call nobody can reproduce.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "faqs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "bank_id", sa.String(length=36), sa.ForeignKey("banks.id"),
            nullable=False, index=True,
        ),
        sa.Column("question", sa.String(length=400), nullable=False),
        sa.Column("lookup", sa.String(length=420), nullable=False, index=True),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("approved_by", sa.String(length=36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("served", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bank_id", "lookup", name="uq_faq_bank_lookup"),
    )


def downgrade() -> None:
    op.drop_table("faqs")
