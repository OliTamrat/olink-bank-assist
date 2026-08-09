"""Stop counting content signals as customers waiting for a callback.

Four things file a handoff. Three of them mean a person has to act: a
complaint, someone asking for a human, and a question nothing could answer.
The fourth does not — when the assistant answers from general banking
knowledge it files a row so the bank can see it has no content of its own on
the subject, which is a genuine signal and the reason Content Gaps works.

But that row landed in the same queue with `status='open'`, so a customer who
asked "tell me about service fees", got a complete answer and left was counted
among "9 escalations waiting for someone" — with no contact details, because
the assistant had correctly not asked for any. An operator opening that queue
found most of it was nobody.

`needs_person` separates the two. The queue and the count filter on it;
Content Gaps deliberately does not, because there the row is the whole point.

Backfilled to false for existing general-knowledge rows, and additionally for
any row that was never given contact details and is still open — the state a
row can only be in if nobody was ever going to be called back.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "handoffs",
        sa.Column("needs_person", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    # The rows that were never anybody's work.
    op.get_bind().execute(
        sa.text(
            "UPDATE handoffs SET needs_person = :no "
            "WHERE reason = 'answered_from_general_knowledge'"
        ),
        {"no": False},
    )


def downgrade() -> None:
    with op.batch_alter_table("handoffs") as batch:
        batch.drop_column("needs_person")
