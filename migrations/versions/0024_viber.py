"""Add banks.viber_auth_token — the second messaging channel.

One column, not two, and the difference from Telegram is worth recording
because it is the part that is easy to get wrong.

Telegram lets us choose a webhook secret and hands it back in a header, so
that channel stores a token to send with and a secret to check against.
Viber has no such secret: it signs the request body with **the auth token
itself**, HMAC-SHA256, in `X-Viber-Content-Signature`. So there is nothing
separate to store, and a `viber_webhook_secret` column would be a field that
is always null — a standing invitation for someone to "fix" it later by
inventing a second credential Viber will never send.

Nullable, no backfill: a bank has no Viber presence until someone pastes a
token into Settings.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "banks", sa.Column("viber_auth_token", sa.String(length=128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("banks", "viber_auth_token")
