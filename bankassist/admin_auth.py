"""Sessions for admin users: issue, resolve, revoke.

Server-side by design. The whole feature is being able to remove someone, and
a stateless token cannot be revoked before it expires — a disabled account
would keep working until its JWT aged out, which is precisely the failure this
replaces.

The cost is a database read per request. That is the correct trade here and
should be a known property rather than a surprise: it couples the admin panel
to database health in a way a JWT would not.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AdminSession, User

# Absolute, with no sliding renewal. A session that extends itself on every
# request never ends, which is not a session — it is a password that happens
# to live in a cookie. Eight hours is a working day: long enough not to
# interrupt someone working a queue, short enough that a forgotten browser on
# a shared branch machine is not a standing door.
SESSION_LIFETIME = timedelta(hours=8)

COOKIE_NAME = "ba_session"


def _hash(token: str) -> str:
    """SHA-256, not argon2.

    Deliberately different from password hashing. A session token is 256 bits
    of our own randomness, so there is nothing to brute-force and no reason to
    pay a memory-hard cost on every single request. Passwords are low-entropy
    and human-chosen; these are not, and treating them the same would be
    cargo-culting the expensive option.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def issue(
    db: Session, user: User, *, ip: str | None = None, user_agent: str | None = None
) -> tuple[str, AdminSession]:
    """Create a session. Returns (plaintext token, row).

    The plaintext is returned once and never stored — only its hash goes to
    the database, so a database read cannot yield a working credential.
    """
    token = secrets.token_urlsafe(32)
    row = AdminSession(
        user_id=user.id,
        token_hash=_hash(token),
        expires_at=datetime.now(UTC) + SESSION_LIFETIME,
        created_ip=ip,
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(row)
    db.flush()
    return token, row


def resolve(db: Session, token: str | None) -> User | None:
    """The user this token belongs to, or None.

    Returns None for every failure — expired, revoked, unknown, or belonging
    to a disabled user — because the caller has nothing useful to do with the
    distinction and a response that revealed it would be an oracle.
    """
    if not token:
        return None
    row = db.execute(
        select(AdminSession).where(AdminSession.token_hash == _hash(token))
    ).scalar_one_or_none()
    if row is None:
        return None
    # Constant-time even though the lookup was by hash. The index makes the
    # query itself a timing signal only in theory, but comparing with == here
    # would be the one place in this file where a habit slips.
    if not hmac.compare_digest(row.token_hash, _hash(token)):
        return None
    now = datetime.now(UTC)
    if row.revoked_at is not None or _aware(row.expires_at) <= now:
        return None
    user = db.get(User, row.user_id)
    # Checked on every request, not only at login. Disabling someone has to
    # take effect against sessions they already hold — otherwise "remove this
    # person" means "remove them in up to eight hours", and the feature is
    # theatre.
    if user is None or not user.is_active:
        return None
    return user


def revoke(db: Session, token: str) -> None:
    row = db.execute(
        select(AdminSession).where(AdminSession.token_hash == _hash(token))
    ).scalar_one_or_none()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)


def revoke_all_for_user(db: Session, user_id: str) -> int:
    """Every session this person holds. Returns how many were live.

    Called when an account is disabled or its password changes. A password
    change that left old sessions alive would mean the person who knew the old
    password keeps their access, which is the opposite of what changing it is
    for.
    """
    rows = db.execute(
        select(AdminSession).where(
            AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None)
        )
    ).scalars().all()
    now = datetime.now(UTC)
    for row in rows:
        row.revoked_at = now
    return len(rows)


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes even for timezone=True columns.

    Comparing one of those to an aware `now` raises TypeError, which would
    surface as a 500 on every authenticated request under SQLite and never in
    Postgres — a difference between the test database and production is the
    worst place for a bug to live.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
