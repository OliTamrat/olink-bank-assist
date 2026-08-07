"""Record what the assistant actually did on each turn.

Analytics needs to say how many questions were answered from the bank's own
content, how many fell back to general guidance, and how many needed a person.
All of that is *nearly* derivable from what is already stored — but not quite:
handoffs are linked to a conversation, not to a message, so attributing one to
the turn that caused it means matching on timestamps. That is fragile, and it
would re-encode agent.handle_message()'s branch logic in SQL, where it would
silently drift the first time a branch changes.

The assistant knows the answer at the moment it replies. Writing it down makes
every metric a GROUP BY that cannot disagree with the code.

Nullable with no backfill on purpose: rows written before this migration have
no honest value to give them, and inventing one would put guesses into the
numbers a bank is being asked to trust. The API reports them as "unclassified"
instead.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("outcome", sa.String(32), nullable=True))
    op.create_index("ix_messages_bank_outcome", "messages", ["bank_id", "outcome"])


def downgrade() -> None:
    op.drop_index("ix_messages_bank_outcome", table_name="messages")
    op.drop_column("messages", "outcome")
