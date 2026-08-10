"""Link a translated answer to the answer it was translated from.

Without it there is no way to say "the Amharic of THIS question". Two things
break, and the second is the one that loses work:

- The review sheet cannot put an answer and its translations on one row, so a
  reviewer gets 800 unrelated lines instead of 160 questions with four cells
  each to correct.
- Re-running a translation batch cannot tell whether a language is already
  covered. Matching on the lookup key almost works and fails exactly when it
  matters: a reviewer who corrects the Amharic *wording of the question*
  changes its key, so the next batch sees no Amharic and writes a second row
  beside the corrected one.

Nullable, no backfill. Everything already there was written by a person in its
own language and was translated from nothing.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("faqs", sa.Column("source_faq_id", sa.String(36), nullable=True))
    op.create_index("ix_faqs_source_faq_id", "faqs", ["source_faq_id"])


def downgrade() -> None:
    op.drop_index("ix_faqs_source_faq_id", table_name="faqs")
    op.drop_column("faqs", "source_faq_id")
