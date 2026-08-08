"""Roles as data, and an audit trail that can name a person.

Three changes, one theme: the system stops asserting things it does not know.

`roles` + `role_permissions` replace the role *name* that 0010 stored on
`users`. A name compared in a route handler makes every new distinction a code
change plus a migration and gives no tenant its own org structure. Rows make
the permission matrix a table an access review can be handed directly.

Roles are per-bank, including the two built-ins, which are seeded once per
tenant here and again whenever a tenant is created. Global rows with a
nullable `bank_id` were the obvious alternative and are worse: every lookup
would need `bank_id = :x OR bank_id IS NULL`, and `UNIQUE(bank_id, name)`
would not actually hold, because Postgres treats NULLs as distinct and would
happily accept two system roles both named `admin`.

`handoffs.resolved_by` is nullable and stays nullable. Rows resolved before
this existed have nobody to name, and one resolved through the break-glass
token still has nobody — a tenant-wide token is not a person.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-08
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


# Copied, not imported from bankassist.permissions.
#
# A migration is a statement about what the schema did on the day it ran. If it
# imported the live registry, adding a permission later would silently change
# what this already-applied migration claims to have seeded, and re-running it
# on a fresh database would produce a different result from the one production
# actually got. Duplication is the correct cost here.
_BUILTIN_ROLES: dict[str, tuple[str, ...]] = {
    "operator": (
        "analytics.read",
        "conversations.read",
        "handoffs.read",
        "gaps.read",
        "documents.read",
        "handoffs.resolve",
    ),
    "admin": (
        "analytics.read",
        "conversations.read",
        "handoffs.read",
        "gaps.read",
        "documents.read",
        "handoffs.resolve",
        "documents.write",
        "integrations.manage",
        "users.manage",
    ),
}

_DESCRIPTIONS = {
    "operator": "Works the escalation queue. Reads everything, changes nothing "
    "the assistant says.",
    "admin": "Manages content, integrations and colleagues.",
}


def upgrade() -> None:
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bank_id", sa.String(36), sa.ForeignKey("banks.id"), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column(
            "is_builtin", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bank_id", "name", name="uq_roles_bank_name"),
    )
    op.create_index("ix_roles_bank_id", "roles", ["bank_id"])

    role_permissions = op.create_table(
        "role_permissions",
        sa.Column(
            "role_id", sa.String(36), sa.ForeignKey("roles.id"), primary_key=True
        ),
        sa.Column("permission", sa.String(64), primary_key=True),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])

    # Seed the built-ins for every tenant that already exists.
    conn = op.get_bind()
    now = datetime.now(UTC)
    bank_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM banks"))]

    role_rows = []
    grant_rows = []
    # (bank_id, role_name) -> role_id, so the users backfill below can resolve
    # a name to an id without re-reading the table.
    lookup: dict[tuple[str, str], str] = {}
    for bank_id in bank_ids:
        for name, perms in _BUILTIN_ROLES.items():
            role_id = str(uuid.uuid4())
            lookup[(bank_id, name)] = role_id
            role_rows.append(
                {
                    "id": role_id,
                    "bank_id": bank_id,
                    "name": name,
                    "description": _DESCRIPTIONS[name],
                    "is_builtin": True,
                    "created_at": now,
                }
            )
            grant_rows.extend(
                {"role_id": role_id, "permission": p} for p in perms
            )
    if role_rows:
        op.bulk_insert(roles, role_rows)
        op.bulk_insert(role_permissions, grant_rows)

    # users.role (a name) becomes users.role_id (a reference).
    #
    # Added nullable, backfilled, then made NOT NULL — the only order that
    # works on a table that already has rows.
    op.add_column("users", sa.Column("role_id", sa.String(36), nullable=True))

    for (bank_id, name), role_id in lookup.items():
        conn.execute(
            sa.text(
                "UPDATE users SET role_id = :role_id "
                "WHERE bank_id = :bank_id AND role = :name"
            ),
            {"role_id": role_id, "bank_id": bank_id, "name": name},
        )

    # Anyone whose role string matched neither built-in — impossible through
    # the API, which validates against the same two names, but a hand-edited
    # row would otherwise become NOT NULL-violating and abort the deploy.
    # Falling back to `operator` fails closed: the least privilege available,
    # never `admin`.
    for bank_id in bank_ids:
        conn.execute(
            sa.text(
                "UPDATE users SET role_id = :role_id "
                "WHERE bank_id = :bank_id AND role_id IS NULL"
            ),
            {"role_id": lookup[(bank_id, "operator")], "bank_id": bank_id},
        )

    # batch_alter_table because SQLite cannot ALTER a column's nullability or
    # drop one in place — it rebuilds the table. A no-op wrapper on Postgres.
    with op.batch_alter_table("users") as batch:
        batch.alter_column("role_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key("fk_users_role_id", "roles", ["role_id"], ["id"])
        batch.drop_column("role")
    op.create_index("ix_users_role_id", "users", ["role_id"])

    with op.batch_alter_table("handoffs") as batch:
        batch.add_column(sa.Column("resolved_by", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_handoffs_resolved_by", "users", ["resolved_by"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("handoffs") as batch:
        batch.drop_constraint("fk_handoffs_resolved_by", type_="foreignkey")
        batch.drop_column("resolved_by")

    # Restore the name column before dropping the tables it would be derived
    # from, so the down path never leaves users with no role information at
    # all — a downgrade that loses which people were administrators would be
    # worse than one that fails.
    op.add_column(
        "users",
        sa.Column("role", sa.String(32), nullable=False, server_default="operator"),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE users SET role = ("
            "  SELECT roles.name FROM roles WHERE roles.id = users.role_id"
            ") WHERE role_id IS NOT NULL"
        )
    )

    op.drop_index("ix_users_role_id", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("fk_users_role_id", type_="foreignkey")
        batch.drop_column("role_id")

    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_index("ix_roles_bank_id", table_name="roles")
    op.drop_table("roles")
