"""Point CBE's logo at CBE's own host.

The seed now carries the URL, and the seed only applies to tenants that do not
exist yet — so on its own it does nothing for the CBE tenant that is already
live. Same shape as 0012, which corrected the brand colour, and for the same
reason.

**Only if the field is still empty.** A logo set through the Branding panel is
CBE's own decision, and a deploy that overwrites it would change what
customers see in the chat header on the bank's website. That is the one place
in this product where re-imposing a default is worst, so the guard is `IS
NULL` rather than a match on some previous value: there is no earlier URL of
ours to recognise, and anything present was put there by a person.

The URL is a hotlink to combanketh.et rather than a copy we serve. That is a
deliberate improvement over what the panel had been pointed at by hand — a
logo-aggregator site, where nobody at CBE controls the file — but it still
inherits that host's uptime and whatever hotlink policy it has. Mirroring the
image behind our own domain is the durable fix and is not this migration.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_CBE_LOGO = "https://combanketh.et/uploads/Logo_849ddbfbe1.jpg"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE banks SET logo_url = :url "
            "WHERE slug = 'cbe' AND (logo_url IS NULL OR logo_url = '')"
        ),
        {"url": _CBE_LOGO},
    )


def downgrade() -> None:
    # Symmetrically guarded: clear it only if it is still the value this
    # migration set, so a logo chosen afterwards survives a rollback.
    op.get_bind().execute(
        sa.text("UPDATE banks SET logo_url = NULL WHERE slug = 'cbe' AND logo_url = :url"),
        {"url": _CBE_LOGO},
    )
