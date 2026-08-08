"""Seeding and reading the per-bank role rows.

`permissions.py` says what capabilities exist; this reads which of them a
given person holds.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import permissions
from .models import Role, RolePermission, User


def ensure_builtin_roles(db: Session, bank_id: str) -> dict[str, Role]:
    """Seed `operator` and `admin` for a bank. Idempotent.

    Called when a tenant is created and again from the migration that
    backfills existing tenants. It returns existing rows untouched rather than
    resetting them, because a bank that has narrowed its own `operator` must
    not have that quietly undone the next time this runs — the built-ins are a
    starting point, not a policy the product keeps re-imposing.
    """
    existing = {
        role.name: role
        for role in db.execute(
            select(Role).where(Role.bank_id == bank_id)
        ).scalars()
    }
    for name, perms in permissions.BUILTIN_ROLES.items():
        if name in existing:
            continue
        role = Role(
            bank_id=bank_id,
            name=name,
            description=permissions.BUILTIN_DESCRIPTIONS.get(name),
            is_builtin=True,
        )
        db.add(role)
        db.flush()  # assign the id before the grant rows reference it
        for perm in perms:
            db.add(RolePermission(role_id=role.id, permission=perm))
        existing[name] = role
    return existing


def permissions_for_role(db: Session, role_id: str) -> frozenset[str]:
    rows = db.execute(
        select(RolePermission.permission).where(RolePermission.role_id == role_id)
    ).scalars()
    return frozenset(rows)


def permissions_for_user(db: Session, user: User) -> frozenset[str]:
    return permissions_for_role(db, user.role_id)


def user_has(db: Session, user: User, permission: str) -> bool:
    """Whether this person holds this permission.

    A disabled user is refused here as well as at session resolution. Two
    checks for one property is deliberate: this one is the last gate before an
    action happens, and it should not depend on every future caller having
    remembered the first.
    """
    if not user.is_active:
        return False
    return permission in permissions_for_user(db, user)


def role_by_name(db: Session, bank_id: str, name: str) -> Role | None:
    return db.execute(
        select(Role).where(Role.bank_id == bank_id, Role.name == name)
    ).scalar_one_or_none()
