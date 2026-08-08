"""Give the admin panel people instead of one shared token per bank.

Three tables, and the split between the first two is the point.

`users` is who someone is. `user_credentials` is how they prove it. Keeping
them apart is what lets SSO arrive later as another row rather than a rewrite
of everything that touches a user — and it is what lets one person hold a
password and a TOTP secret without a nullable column per method bolted onto
`users`.

`admin_sessions` is server-side on purpose. The entire feature is being able
to remove someone; a stateless token cannot be revoked before it expires,
which defeats the thing it is meant to deliver. `revoked_at` is what makes
"disable this person" take effect on their next request rather than in an
hour.

Nothing is switched over here. `banks.admin_token` keeps working and every
existing route still accepts it — this migration only makes the new path
possible, so a mistake in the routes cannot lock a bank out of its own
dashboard.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bank_id", sa.String(36), sa.ForeignKey("banks.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="operator"),
        # Disabled rather than deleted: an audit entry naming a user id has to
        # still resolve after that person has left the bank.
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Per tenant, not global. The same person administering two banks gets
        # two accounts — merging identities across tenants is a different
        # product, and a shared row would be a cross-tenant join waiting to be
        # written by accident.
        sa.UniqueConstraint("bank_id", "email", name="uq_users_bank_email"),
    )
    op.create_index("ix_users_bank_id", "users", ["bank_id"])

    op.create_table(
        "user_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        # password | totp | oidc. A string rather than an enum so adding a
        # method is not a migration in every environment.
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("secret_hash", sa.Text, nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "kind", name="uq_credentials_user_kind"),
    )
    op.create_index("ix_user_credentials_user_id", "user_credentials", ["user_id"])

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        # The hash, never the token. A database read must not yield a working
        # credential — the same rule the password column follows.
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Unique, not merely indexed: every request looks a session up by this, and
    # a collision would silently hand one person another's session.
    op.create_index(
        "ix_admin_sessions_token_hash", "admin_sessions", ["token_hash"], unique=True
    )
    op.create_index("ix_admin_sessions_user_id", "admin_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_sessions_user_id", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_token_hash", table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_index("ix_user_credentials_user_id", table_name="user_credentials")
    op.drop_table("user_credentials")
    op.drop_index("ix_users_bank_id", table_name="users")
    op.drop_table("users")
