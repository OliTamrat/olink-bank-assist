"""Create a tenant's first administrator — the door ADR-0031 left unattended.

    python -m bankassist.create_admin dashen --email you@bank.et
    python -m bankassist.create_admin dashen --email you@bank.et --role operator

ADR-0031 retired the admin token as a login: it now opens exactly one door,
creating the first administrator, and nothing else. That is the right shape.
What it shipped without is any tooling to walk through it — `show_token` prints
the token and then you are on your own with a hand-written HTTP call.

The cost was not hypothetical. Every tenant was seeded with documents, roles
and **no users**, so every email-and-password sign-in failed on every bank with
"that email and password did not match", which is true and tells nobody
anything. There was no supported command to fix it. This is that command.

**The password is never an argument.** It is read from the terminal with
`getpass`, so it does not reach `argv`, the shell's history file, the process
list on a shared box, or a CI log. That last one is not theoretical either:
this project's four admin tokens were rotated on 2026-08-10 precisely because
one had been exposed in a build log. A `--password` flag would invite the same
mistake, so there isn't one; `--stdin` exists for the scripted case, where the
value comes down a pipe rather than along the command line.

It writes to the database directly, like `show_token`, rather than calling the
API — the operator running it already holds the connection string, which is
strictly more power than any account it can create. It still goes through the
product's own `hash_password` and its own role rows, because a bootstrap that
stored a password differently from the login route would be a second way to
hold a credential, with its own bugs.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from . import passwords, roles
from .db import get_engine, init_db
from .models import Bank, User, UserCredential


def _read_password(from_stdin: bool) -> str | None:
    """The password, or None if the operator failed to confirm it.

    Typed twice, because this is the credential for an account that can read
    every customer conversation the tenant holds and there is no "forgot
    password" behind it.
    """
    if from_stdin:
        # `\r\n` as well as `\n`: this reads from a pipe, and the value on the
        # other end of it is often a secret written by a Windows tool. The same
        # class of invisible character has broken this project's database URL
        # twice — see the BOM note in CLAUDE.md — and a trailing carriage
        # return in a password fails at sign-in with "did not match", which
        # names nothing.
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password (not echoed): ")
    second = getpass.getpass("Again: ")
    if first != second:
        print("Those did not match.", file=sys.stderr)
        return None
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bankassist.create_admin",
        description="Create a tenant's first administrator.",
    )
    parser.add_argument("slug", help="bank slug, e.g. demo, cbe, dashen, awash")
    parser.add_argument("--email", required=True, help="the person's sign-in address")
    parser.add_argument("--name", default=None, help="display name, optional")
    parser.add_argument(
        "--role",
        default="admin",
        help="role name for this bank (default: admin). Only an admin can "
        "then create colleagues, so the first one should almost always be one.",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read the password from stdin instead of prompting, for scripts. "
        "Prefer a pipe or a heredoc over anything that puts it in argv.",
    )
    args = parser.parse_args(argv)

    email = args.email.strip().lower()
    if "@" not in email:
        print(f"{args.email!r} is not an email address", file=sys.stderr)
        return 1

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

        # Seeded before the roles migration, or inserted by hand: a tenant with
        # no role rows cannot have a user at all, and saying so beats a foreign
        # key error. Idempotent, so it costs nothing when they already exist.
        roles.ensure_builtin_roles(db, bank.id)
        db.flush()

        role = roles.role_by_name(db, bank.id, args.role)
        if role is None:
            print(f"{bank.name} has no role named {args.role!r}", file=sys.stderr)
            return 1

        if _email_taken(db, bank.id, email):
            print(f"{email} already has an account at {bank.name}", file=sys.stderr)
            return 1

        existing = db.execute(
            select(User).where(User.bank_id == bank.id)
        ).scalars().all()
        if existing:
            # Not refused. Somebody locked out of their own tenant needs this
            # more than anyone, and holding the connection string is already
            # more power than the account being made. But it is said out loud,
            # because "first administrator" is what this command is for and a
            # surprise second one is worth a sentence.
            print(
                f"Note: {bank.name} already has {len(existing)} account(s). "
                f"The admin token stopped being a login the moment the first "
                f"one existed (ADR-0031); this writes directly to the database."
            )

        secret = _read_password(args.stdin)
        if secret is None:
            return 1
        if len(secret) < passwords.MIN_LENGTH:
            print(
                f"Too short — at least {passwords.MIN_LENGTH} characters.",
                file=sys.stderr,
            )
            return 1

        user = User(
            bank_id=bank.id, email=email, display_name=args.name, role_id=role.id
        )
        db.add(user)
        db.flush()
        db.add(
            UserCredential(
                user_id=user.id,
                kind="password",
                secret_hash=passwords.hash_password(secret),
            )
        )
        db.commit()

    # Deliberately does not echo the password back, not even to confirm it.
    print(f"Created {email} as {args.role} at {bank.name}.")
    print(f"Sign in at /admin with bank {bank.slug!r} and that address.")
    return 0


def _email_taken(db: Session, bank_id: str, email: str) -> bool:
    """One address, one account, per tenant — the same rule the API enforces."""
    return (
        db.execute(
            select(User).where(User.bank_id == bank_id, User.email == email)
        ).scalar_one_or_none()
        is not None
    )


if __name__ == "__main__":
    raise SystemExit(main())
