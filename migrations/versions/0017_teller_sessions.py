"""Teller sessions, and the two permissions that govern them.

Three things, all additive — nothing existing changes shape:

1. The `teller_sessions` table.
2. A `teller` built-in role for every bank that already exists. `ensure_builtin_roles`
   never touches a role that is already there (otherwise a deploy would
   overwrite a bank's own edits), so a tenant created before this migration
   would never acquire the new role on its own. Same gap 0014 closed for
   `audit.read`.
3. `sessions.read` and `teller.serve` on existing built-in `admin` roles.

**Operators deliberately get neither.** Working a queue after the fact and
appearing on video as the bank are different jobs, and a bank certifying staff
for the second should not find that everyone who answers escalations already
has it. That is the whole reason `teller` is a separate role rather than a
column on `operator`.

**Only `is_builtin` roles are touched.** A role a bank defined itself is that
bank's decision, and widening it during a deploy is precisely the failure the
roles-as-data schema was shaped to avoid.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-09
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

_TELLER_ROLE = "teller"
_TELLER_DESCRIPTION = (
    "Speaks to customers live. Sees the conversation they are joining and "
    "nothing else."
)
# What the teller role holds. Mirrors permissions.BUILTIN_ROLES[TELLER] — the
# constant is not imported so that editing the code later cannot silently
# rewrite what a past deploy granted.
_TELLER_PERMISSIONS = (
    "conversations.read",
    "handoffs.read",
    "handoffs.resolve",
    "documents.read",
    "sessions.read",
    "teller.serve",
)
_ADMIN_ADDITIONS = ("sessions.read", "teller.serve")


def upgrade() -> None:
    op.create_table(
        "teller_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bank_id", sa.String(36), nullable=False, index=True),
        sa.Column("conversation_id", sa.String(36), nullable=False, index=True),
        sa.Column("handoff_id", sa.String(36), nullable=True, index=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="requested"),
        sa.Column("scope", sa.String(16), nullable=False, server_default="unverified"),
        sa.Column("verified_method", sa.String(24), nullable=True),
        sa.Column("verified_ref", sa.String(120), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("teller_user_id", sa.String(36), nullable=True),
        sa.Column("channel", sa.String(80), nullable=True),
        sa.Column("media", sa.String(8), nullable=False, server_default="audio"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
    )
    # The queue view is "waiting sessions for this bank, oldest first", and it
    # is polled. Without this it is a full scan of every session the bank has
    # ever had, growing forever.
    op.create_index(
        "ix_teller_sessions_bank_state", "teller_sessions", ["bank_id", "state"]
    )

    conn = op.get_bind()

    # --- the teller role, per bank -------------------------------------
    banks = conn.execute(sa.text("SELECT id FROM banks")).fetchall()
    for (bank_id,) in banks:
        existing = conn.execute(
            sa.text("SELECT id FROM roles WHERE bank_id = :b AND name = :n"),
            {"b": bank_id, "n": _TELLER_ROLE},
        ).fetchone()
        if existing is not None:
            continue  # a bank that already defined "teller" keeps its own
        role_id = str(uuid.uuid4())
        # created_at is supplied explicitly. `Role.created_at` has a
        # PYTHON-side default, not a server default, so a raw INSERT that
        # omits it violates NOT NULL — and the omission is invisible until a
        # bank actually exists at migration time, which on a fresh database it
        # never does. Caught only by seeding a bank BEFORE upgrading.
        conn.execute(
            sa.text(
                "INSERT INTO roles "
                "(id, bank_id, name, description, is_builtin, created_at) "
                "VALUES (:id, :b, :n, :d, :yes, :now)"
            ),
            {
                "id": role_id, "b": bank_id, "n": _TELLER_ROLE,
                "d": _TELLER_DESCRIPTION, "yes": True,
                "now": datetime.now(UTC),
            },
        )
        for perm in _TELLER_PERMISSIONS:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission) "
                    "VALUES (:r, :p)"
                ),
                {"r": role_id, "p": perm},
            )

    # --- the two new permissions on existing admin roles ----------------
    # NOT EXISTS rather than a plain insert: role_permissions has a composite
    # primary key, so re-running against a role that already holds one would
    # abort on a duplicate key instead of no-opping.
    for perm in _ADMIN_ADDITIONS:
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
            {"perm": perm, "yes": True},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for perm in _ADMIN_ADDITIONS:
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission = :p"),
            {"p": perm},
        )
    # Only the built-in teller roles this migration created. A bank that has
    # since defined its own "teller" keeps it, along with anyone assigned to
    # it — dropping a role out from under live users would sign them out of a
    # job they still hold.
    conn.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE role_id IN ("
            "  SELECT id FROM roles WHERE name = :n AND is_builtin = :yes"
            ")"
        ),
        {"n": _TELLER_ROLE, "yes": True},
    )
    conn.execute(
        sa.text("DELETE FROM roles WHERE name = :n AND is_builtin = :yes"),
        {"n": _TELLER_ROLE, "yes": True},
    )
    op.drop_index("ix_teller_sessions_bank_state", table_name="teller_sessions")
    op.drop_table("teller_sessions")
