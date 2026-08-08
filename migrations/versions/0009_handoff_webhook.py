"""Let a bank receive handoffs in its own contact-centre tool.

The admin console is one way to work the queue. A bank that already runs
Freshdesk, Zendesk or an in-house CRM will not adopt a second inbox for a
pilot, and asking them to is how a pilot stalls on a process question rather
than on the product.

Both columns are nullable and default to off. This posts the customer's
question and their contact details to a third-party system, which is personal
data leaving our control — so it happens only when a bank has explicitly
configured a destination, never by default, and never for a tenant that has
not asked for it.

The secret is not optional in practice: without it the receiving system cannot
tell our POST from anyone else's. It is nullable only because the URL and the
secret are set in the same request, and a half-configured row should be
possible to inspect rather than impossible to store.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("banks", sa.Column("handoff_webhook_url", sa.String(500), nullable=True))
    op.add_column("banks", sa.Column("handoff_webhook_secret", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("banks", "handoff_webhook_secret")
    op.drop_column("banks", "handoff_webhook_url")
