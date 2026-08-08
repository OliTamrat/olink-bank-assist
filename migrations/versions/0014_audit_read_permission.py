"""Grant the new audit.read permission to existing built-in admin roles.

The first new permission since roles became data, and it exposes the cost of
that decision: adding one to `permissions.py` grants it to nobody. Roles are
rows, `ensure_builtin_roles` deliberately does not touch a role that already
exists — otherwise every deploy would overwrite a bank's own edits — so a
tenant created last week has an `admin` role that predates this permission and
will never acquire it on its own.

Verified rather than assumed before writing this: the seeded admin role in an
existing database did not hold `audit.read` while the code said it should.

**Only `is_builtin` roles named `admin`.** A role a bank defined itself is that
bank's decision, and quietly widening it during a deploy is precisely the
failure this schema was shaped to avoid. Those banks grant it themselves, which
is the point of the permission being data in the first place.

Operators do not get it. Reviewing colleagues' actions is a management function,
not part of working the queue.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_PERMISSION = "audit.read"


def upgrade() -> None:
    conn = op.get_bind()
    # NOT EXISTS rather than a plain insert: role_permissions has a composite
    # primary key, so re-running against a role that already holds it would
    # abort the migration on a duplicate key instead of no-opping.
    conn.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission) "
            "SELECT r.id, :perm FROM roles r "
            "WHERE r.name = 'admin' AND r.is_builtin = :yes "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM role_permissions p "
            "  WHERE p.role_id = r.id AND p.permission = :perm"
            ")"
        ),
        {"perm": _PERMISSION, "yes": True},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM role_permissions WHERE permission = :perm"),
        {"perm": _PERMISSION},
    )
