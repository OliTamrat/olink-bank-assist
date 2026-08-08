"""What a bank is called, alongside what it is registered as.

"Commercial Bank of Ethiopia" is the registered name. "CBE" is the name
everybody actually uses, and the one on the brand.

A straight rename would have been wrong in both directions. The full name in a
chat header and a sidebar is nobody's name for it and does not fit either. The
short name on a printed report in a board pack — or inside the model's system
prompt, where "CBE" is an ambiguous three letters and the full name is not —
throws away precision exactly where it is wanted.

So both are stored. `short_name` is nullable: a bank with no distinct short
form needs nothing set and `display_name` falls back to the registered name.

Backfills CBE only. The other tenants are already known by their full names —
"Dashen Bank" is what Dashen is called — and inventing abbreviations for them
would be putting words in their mouths.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("banks", sa.Column("short_name", sa.String(64), nullable=True))
    # Guarded on the registered name rather than set unconditionally, so a
    # tenant that has already chosen its own brand name keeps it.
    op.get_bind().execute(
        sa.text(
            "UPDATE banks SET short_name = 'CBE' "
            "WHERE slug = 'cbe' AND short_name IS NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("banks") as batch:
        batch.drop_column("short_name")
