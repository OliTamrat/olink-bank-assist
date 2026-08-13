"""Second factor for admin accounts: TOTP replay state, recovery codes, and a
half-authenticated session that cannot act.

Four changes, and each one exists to close a specific way MFA gets shipped
broken.

`user_credentials.last_used_step` is what makes a one-time password one-time.
Without it a code is valid for its whole 30-second window plus the drift
allowance either side, so a code read over a shoulder or off a phone's lock
screen can be typed by somebody else while it is still good. Storing the
highest step already spent lets `totp.verify` refuse anything at or below it.
Nullable: a credential that has never been used has spent no step, and 0 is a
real step number rather than a stand-in for "none".

`recovery_codes` is a table rather than more columns on `user_credentials`,
because that table has a unique constraint on (user_id, kind) and a person
holds ten codes at once. Each row is one code: its hash, and when it was
spent. Rows are kept after use rather than deleted, so "you have three codes
left" is answerable and so a support conversation can distinguish a code that
was never issued from one already used.

`admin_sessions.pending_mfa` is the half-authenticated state, and putting it
HERE rather than in a separate challenge store is the design decision worth
recording. A password that has been verified but not yet seconded has to live
somewhere between the two requests. A parallel challenge table would be a
second thing that grants access, with its own expiry and revocation to get
right — and every route in the product already goes through
`admin_auth.resolve()`. Marking the session instead means resolve() is the
single place that decides, and it fails closed: a pending session resolves to
nobody, so a route that forgot about MFA is not a route that leaks.

`banks.require_mfa` is what a bank's security questionnaire asks for. Default
false, deliberately: switching it on for a tenant whose admins have not
enrolled yet would lock every one of them out at once.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_credentials",
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "admin_sessions",
        sa.Column(
            "pending_mfa", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "banks",
        sa.Column(
            "require_mfa", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        # SHA-256 hex. The code itself is shown once, at generation, and is
        # never recoverable from here — the same rule the password column and
        # the session token follow.
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # The lookup on every recovery login: this user's unspent codes.
    op.create_index(
        "ix_recovery_codes_user_hash", "recovery_codes", ["user_id", "code_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_recovery_codes_user_hash", table_name="recovery_codes")
    op.drop_table("recovery_codes")
    op.drop_column("banks", "require_mfa")
    op.drop_column("admin_sessions", "pending_mfa")
    op.drop_column("user_credentials", "last_used_step")
