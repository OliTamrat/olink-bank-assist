"""Set a new password for an existing account — the recovery this product had none of.

    python -m bankassist.reset_password dashen --email you@bank.et

There is no "forgot password" anywhere in this product. `change_own_password`
is the only route that writes a password and it requires the current one, so
an administrator who forgets theirs on a tenant that has users is locked out
completely: the admin token retired the moment that account was created
(ADR-0031), no colleague can reset it, and MFA recovery codes recover the
second factor rather than the first. The only remaining path was hand-written
SQL against production.

That is a routine failure at any bank, not an exotic one, and the answer
cannot be "make yourself a second account and abandon the first" — which is
all `create_admin` could offer.

Same discipline as `create_admin`, for the same reasons:

- **The password is never an argument.** `getpass`, twice, echoed nowhere.
  `--stdin` is the scripted case. This project rotated four admin tokens on
  2026-08-10 after one appeared in a build log.
- It writes to the database directly. Whoever runs this already holds the
  connection string, which is strictly more power than the account it repairs.
- It goes through the product's own `hash_password`, so a reset is not a
  second place a password is written.

**Every other session is revoked**, exactly as `change_own_password` does. A
reset that left old sessions alive would leave whoever knew the old password
still signed in — the opposite of what resetting it is for, and the precise
case where someone resets it *because* they think they were compromised.

**It does not touch the second factor**, and that is deliberate rather than
unfinished. Clearing MFA from a command line would turn ADR-0027's second
factor into something one command removes, which is a guardrail decision and
not a convenience one. It reports whether a second factor is enrolled and how
many recovery codes remain, so the person running it knows whether a new
password is actually enough to get in.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from . import admin_auth, passwords
from .db import get_engine, init_db
from .models import AuditLog, Bank, RecoveryCode, User, UserCredential

ACTOR = "reset-password-cli"
"""What the audit log records.

Named for the mechanism rather than a person, on the same principle as
`TOKEN_ACTOR`: whoever ran this held the connection string and the log has no
honest way to say who that was. Writing the account's own id here would read
as the user resetting their own password, which is the one thing this command
exists because they could not do.
"""


def _read_password(from_stdin: bool) -> str | None:
    """The new password, or None if the operator failed to confirm it."""
    if from_stdin:
        # `\r\n` as well as `\n` — see the note in create_admin: this reads
        # from a pipe, and secrets written by Windows tooling carry a CR that
        # then fails at sign-in with "did not match", which names nothing.
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("New password (not echoed): ")
    second = getpass.getpass("Again: ")
    if first != second:
        print("Those did not match.", file=sys.stderr)
        return None
    return first


def _second_factor_note(db: Session, user: User) -> str | None:
    """Whether a new password is actually enough to sign in as this person.

    Worth a sentence rather than silence: someone who has lost their
    authenticator and reads "password reset" reasonably concludes they are
    back in, tries it, and meets a code prompt they cannot answer.
    """
    totp = db.execute(
        select(UserCredential).where(
            UserCredential.user_id == user.id, UserCredential.kind == "totp"
        )
    ).scalar_one_or_none()
    if totp is None or totp.verified_at is None:
        return None
    left = len(
        db.execute(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
            )
        ).scalars().all()
    )
    return (
        f"This account has two-factor enabled, so the new password alone will "
        f"not sign it in — you also need the authenticator, or one of the "
        f"{left} unused recovery code(s). This command deliberately does not "
        f"remove a second factor."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bankassist.reset_password",
        description="Set a new password for an existing account.",
    )
    parser.add_argument("slug", help="bank slug, e.g. demo, cbe, dashen, awash")
    parser.add_argument("--email", required=True, help="the account to reset")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read the password from stdin instead of prompting, for scripts. "
        "Prefer a pipe or a heredoc over anything that puts it in argv.",
    )
    args = parser.parse_args(argv)

    email = args.email.strip().lower()

    init_db()
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as db:
        bank = db.execute(
            select(Bank).where(Bank.slug == args.slug)
        ).scalar_one_or_none()
        if bank is None:
            known = ", ".join(
                sorted(b.slug for b in db.execute(select(Bank)).scalars())
            )
            print(
                f"No bank with slug {args.slug!r}. This database has: {known or 'none'}",
                file=sys.stderr,
            )
            return 1

        user = db.execute(
            select(User).where(User.bank_id == bank.id, User.email == email)
        ).scalar_one_or_none()
        if user is None:
            # Deliberately counts rather than lists. An address is personal
            # data and this command runs in terminals and CI logs; the count
            # answers "did I use the right tenant" without printing anybody's
            # email into a build log.
            total = len(
                db.execute(
                    select(User).where(User.bank_id == bank.id)
                ).scalars().all()
            )
            print(
                f"No account for {email} at {bank.name}. "
                f"That tenant has {total} account(s)."
                + (
                    " With none at all, this is the wrong command — "
                    "use `python -m bankassist.create_admin` to make the first one."
                    if total == 0
                    else ""
                ),
                file=sys.stderr,
            )
            return 1

        secret = _read_password(args.stdin)
        if secret is None:
            return 1
        if len(secret) < passwords.MIN_LENGTH:
            print(
                f"Too short — at least {passwords.MIN_LENGTH} characters.",
                file=sys.stderr,
            )
            return 1

        credential = db.execute(
            select(UserCredential).where(
                UserCredential.user_id == user.id,
                UserCredential.kind == "password",
            )
        ).scalar_one_or_none()
        if credential is None:
            # An account created through a path that never set one. Rare, but
            # refusing here would be a lockout with a row that says the
            # account exists — so write the credential rather than error.
            credential = UserCredential(
                user_id=user.id, kind="password", secret_hash=""
            )
            db.add(credential)
        credential.secret_hash = passwords.hash_password(secret)

        revoked = admin_auth.revoke_all_for_user(db, user.id)
        db.add(
            AuditLog(
                bank_id=bank.id,
                actor=ACTOR,
                action="password_reset",
                entity_type="user",
                entity_id=str(user.id),
                # The address, never the password and never the hash. The same
                # rule the rest of the audit log follows.
                log_metadata={"email": user.email, "sessions_revoked": revoked},
            )
        )
        db.commit()

        note = _second_factor_note(db, user)

    print(f"Password reset for {email} at {bank.name}.")
    print(f"{revoked} existing session(s) revoked.")
    if note:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
