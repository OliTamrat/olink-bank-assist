"""Capture a way to reach the customer when a question is handed to a person.

Every handoff reply already promised that "our customer service team can follow
up with you", and the product had captured no name, no number and no email to
follow up on. On the web widget there is no identity at all. The promise was
unkeepable, which is worse than not making it.

Contact lives in two places on purpose. The conversation holds the live value,
so a second handoff in the same chat inherits it instead of asking twice. The
handoff holds a snapshot, so an operator working the queue sees who to call on
the row itself rather than joining back to a conversation.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("contact_phone", sa.String(40), nullable=True))
    op.add_column(
        "conversations",
        sa.Column(
            "awaiting_contact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("handoffs", sa.Column("contact_name", sa.String(80), nullable=True))
    op.add_column("handoffs", sa.Column("contact_phone", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("handoffs", "contact_phone")
    op.drop_column("handoffs", "contact_name")
    op.drop_column("conversations", "awaiting_contact")
    op.drop_column("conversations", "contact_phone")
