"""Add documents.source_url.

Where an article came from. Two jobs, and the second is the one that makes
importing usable rather than a one-shot:

- Provenance. "Where did this text come from" is the first question a bank's
  compliance reviewer asks about content their assistant is quoting, and
  "somebody pasted it" is not an answer.
- Idempotence. Re-importing a page a bank has updated has to REPLACE what it
  imported last time. Without a source, the only way to match is the heading —
  which changes precisely when the page is rewritten, and the failure mode is
  a knowledge base holding both the old fee and the new one with nothing to
  say which is current.

Nullable, no backfill: everything already there was written by hand in the
admin and has no source but a person.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("source_url", sa.String(length=500), nullable=True)
    )
    op.create_index("ix_documents_source", "documents", ["bank_id", "source_url"])


def downgrade() -> None:
    op.drop_index("ix_documents_source", table_name="documents")
    op.drop_column("documents", "source_url")
