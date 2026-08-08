"""Correct CBE's brand colour, once, without overruling a later choice.

The seed gave CBE `#7a1f2b`, a maroon. CBE's own site is purple. The seed only
applies to tenants that do not exist yet, so changing it there fixes nothing
for the tenant that is already live — hence a migration.

Guarded on the old value. If CBE has since set its own colour through the
Branding panel, this leaves it alone: a deploy that re-imposes our defaults
over a tenant's own choice is the same failure the role seeding was written to
avoid, and it would be worse here because it changes what customers see on the
bank's website.

The new value was read off combanketh.et rather than from a brand book, so it
is a better default and not an authority. Branding is editable in the panel
precisely so this kind of guess never needs another migration.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_SEEDED_MAROON = "#7a1f2b"
_CBE_PURPLE = "#722282"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE banks SET primary_color = :new "
            "WHERE slug = 'cbe' AND primary_color = :old"
        ),
        {"new": _CBE_PURPLE, "old": _SEEDED_MAROON},
    )


def downgrade() -> None:
    # Symmetrically guarded: only reverse the change this migration made, so a
    # colour chosen after it ran survives a rollback.
    op.get_bind().execute(
        sa.text(
            "UPDATE banks SET primary_color = :old "
            "WHERE slug = 'cbe' AND primary_color = :new"
        ),
        {"new": _CBE_PURPLE, "old": _SEEDED_MAROON},
    )
