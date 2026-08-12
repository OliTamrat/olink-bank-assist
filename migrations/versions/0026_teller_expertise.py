"""Add users.teller_departments and teller_sessions.department.

Which desks a teller actually knows, so a waiting customer with a cards
question is offered first to somebody who works cards — the same shape as
language routing (0019), because it is the same problem: not every teller can
serve every customer equally well, and the queue order is where that
knowledge pays out.

`users.teller_departments` follows 0019 exactly: nullable, no backfill, and
NULL or [] both read as "not declared" — which routing treats as "can take
anything". Every existing teller is undeclared on the morning this ships, and
a stricter reading would empty every queue at once and look like an outage.
Declaring desks narrows what is offered to you first; it never takes work
away.

`teller_sessions.department` is what the customer's question is about,
classified from their own words at the moment they ask for a person — the
same rules `departments.classify` already applies to every escalation.
Nullable, no backfill: an old session's conversation could be re-classified,
but that would need the application's rules inside a schema change, and those
rules will have moved on by the time this runs against a real database
(0020's argument, unchanged). A null department routes like an undeclared
teller reads: it matches everyone.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("teller_departments", sa.JSON(), nullable=True)
    )
    op.add_column(
        "teller_sessions",
        sa.Column("department", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("teller_sessions", "department")
    op.drop_column("users", "teller_departments")
