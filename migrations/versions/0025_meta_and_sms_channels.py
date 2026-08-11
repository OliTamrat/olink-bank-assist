"""Credentials for the Meta channels and SMS.

Completes the channel surface: every channel in the catalogue is now built,
and what remains for each is a credential its owner supplies.

**Why the Meta columns are shared rather than one set per product.** WhatsApp,
Messenger and Instagram Direct are three products of one Meta app. They are
delivered to one callback URL, and every one of them is signed with the SAME
app secret — so an app secret per product would be three columns always
holding the same value, and the first person to set only one of them would
get a channel that rejects everything with no clue why. `meta_app_secret` and
`meta_verify_token` are per-tenant; only the send-side credentials differ per
product, because those genuinely do.

**Why SMS is four columns and not one.** Unlike every other channel here,
SMS has no single vendor API — it goes through whichever aggregator the bank
has an agreement with, and in Ethiopia that means Ethio Telecom. So the
outbound side is stored as a URL, an auth header and a sender id rather than
a token for a service we have hard-coded, and the inbound side gets its own
shared secret because an aggregator will not sign bodies the way Meta does.
See `bankassist/sms.py` for the contract and its limits.

All nullable, no backfill. A bank has no presence on any of these until
someone pastes credentials into Settings.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# (column, length) — every one nullable.
_COLUMNS = (
    # Shared by all three Meta products.
    ("meta_app_secret", 128),
    ("meta_verify_token", 64),
    # WhatsApp Cloud API: the number messages are sent from, and its token.
    ("whatsapp_phone_number_id", 64),
    ("whatsapp_access_token", 512),
    # Messenger: a Page access token.
    ("messenger_page_token", 512),
    # Instagram Direct: the token for the professional account's linked Page.
    ("instagram_access_token", 512),
    # SMS, via whatever aggregator the bank holds an agreement with.
    ("sms_inbound_secret", 64),
    ("sms_send_url", 500),
    ("sms_auth_header", 512),
    ("sms_sender_id", 32),
)


def upgrade() -> None:
    for name, length in _COLUMNS:
        op.add_column(
            "banks", sa.Column(name, sa.String(length=length), nullable=True)
        )


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("banks", name)
