"""Add banks.allow_general_knowledge.

Lets the assistant answer universally-standard banking questions (how to use an
ATM, what a PIN is) when the bank's own knowledge base has nothing — bounded so
it can never state a fee, limit, requirement or anything specific to the bank.
Per-tenant because a compliance-conservative bank will want it off.

Defaults to true: an assistant that cannot explain what a PIN is looks broken,
and the boundary is enforced in the prompt and asserted in tests.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "banks",
        sa.Column(
            "allow_general_knowledge",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("banks", "allow_general_knowledge")
