"""Authorization: what each role can reach, and what the policy must not drift from.

The route-coverage tests near the bottom are the ones that earn their keep.
Every per-role assertion here can pass while a newly added admin route sits
completely unguarded — so two tests read the live route table instead of a
list someone remembered to update.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import permissions, roles
from bankassist.api import Principal, app
from bankassist.models import AuditLog, Handoff, Role, RolePermission, User

_FIXTURE = "pytest-fixture-value"
PW = f"{_FIXTURE}-original"


def _headers(bank: Any) -> dict[str, str]:
    return {"X-Admin-Token": bank.admin_token}


def _make_user(
    client: TestClient, bank: Any, email: str = "ops@bank.et", role: str = "operator"
) -> dict[str, Any]:
    resp = client.post(
        "/admin/api/demo/users",
        headers=_headers(bank),
        json={"email": email, "password": PW, "role": role},
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _signed_in(client: TestClient, bank: Any, role: str) -> TestClient:
    """A SEPARATE client holding a session for a user with this role.

    Returning `client` itself was the first version and was wrong in a way
    worth recording: the cookie jar is per-client, so signing in on the shared
    fixture left every later "unauthenticated" or "token only" call in the
    same test carrying a session. Two tests passed a session off as the
    break-glass token and asserted the wrong thing entirely.
    """
    _make_user(client, bank, email=f"{role}@bank.et", role=role)
    session_client = TestClient(client.app)
    resp = session_client.post(
        "/admin/api/demo/login", json={"email": f"{role}@bank.et", "password": PW}
    )
    assert resp.status_code == 200, resp.text
    return session_client


# ------------------------------------------------------------------ the roles


def test_every_tenant_is_seeded_with_both_builtin_roles(
    db_session: Session, demo_bank: Any
) -> None:
    names = {
        r.name
        for r in db_session.execute(
            select(Role).where(Role.bank_id == demo_bank.id)
        ).scalars()
    }
    assert names == {"operator", "admin"}


def test_seeding_is_idempotent_and_does_not_undo_a_banks_own_edit(
    db_session: Session, demo_bank: Any
) -> None:
    """A bank narrowing its own role must not be quietly overruled.

    This is the property that makes roles data rather than configuration the
    product re-imposes: seeding runs on every deploy, so if it reset grants,
    every tenant's org structure would silently revert on a Tuesday.
    """
    operator = roles.role_by_name(db_session, demo_bank.id, "operator")
    assert operator is not None
    db_session.execute(
        RolePermission.__table__.delete().where(
            RolePermission.role_id == operator.id,
            RolePermission.permission == permissions.Perm.GAPS_READ,
        )
    )
    db_session.commit()

    roles.ensure_builtin_roles(db_session, demo_bank.id)
    db_session.commit()

    assert permissions.Perm.GAPS_READ not in roles.permissions_for_role(
        db_session, operator.id
    )
    assert (
        len(
            [
                r
                for r in db_session.execute(
                    select(Role).where(Role.bank_id == demo_bank.id)
                ).scalars()
            ]
        )
        == 2
    ), "seeding twice must not create duplicate roles"


def test_admin_holds_every_permission_the_registry_defines() -> None:
    """If they diverge, a new permission is unreachable until someone notices.

    Listed explicitly in BUILTIN_ROLES rather than computed from ALL, so this
    test failing is the intended prompt to decide whether admins should hold a
    newly added permission — not a rubber stamp.
    """
    assert set(permissions.BUILTIN_ROLES[permissions.ADMIN]) == set(permissions.ALL)


def test_operator_cannot_change_what_the_assistant_says() -> None:
    operator = set(permissions.BUILTIN_ROLES[permissions.OPERATOR])
    assert permissions.Perm.DOCUMENTS_WRITE not in operator
    assert permissions.Perm.INTEGRATIONS_MANAGE not in operator
    assert permissions.Perm.USERS_MANAGE not in operator


# ------------------------------------------------------------ enforcement


def test_an_operator_may_work_the_queue(client: TestClient, demo_bank: Any) -> None:
    c = _signed_in(client, demo_bank, "operator")
    assert c.get("/admin/api/demo/handoffs").status_code == 200
    assert c.get("/admin/api/demo/documents").status_code == 200


def test_an_operator_may_not_rewrite_the_content(
    client: TestClient, demo_bank: Any
) -> None:
    """The sharpest boundary in the product.

    Someone who can edit a fee schedule changes what every customer is told a
    transfer costs. That is a different job from answering an escalation.
    """
    c = _signed_in(client, demo_bank, "operator")
    resp = c.post(
        "/admin/api/demo/documents",
        json={"title": "Fees", "content": "Transfers are free.", "language": "en"},
    )
    assert resp.status_code == 403


def test_an_operator_may_not_repoint_the_handoff_webhook(
    client: TestClient, demo_bank: Any
) -> None:
    """Where customers' names and phone numbers get delivered."""
    c = _signed_in(client, demo_bank, "operator")
    resp = c.post(
        "/admin/api/demo/handoff-webhook", json={"url": "https://attacker.example/x"}
    )
    assert resp.status_code == 403


def test_an_operator_may_not_create_colleagues(
    client: TestClient, demo_bank: Any
) -> None:
    """Otherwise every permission above is one self-promotion away."""
    c = _signed_in(client, demo_bank, "operator")
    resp = c.post(
        "/admin/api/demo/users",
        json={"email": "new@bank.et", "password": PW, "role": "admin"},
    )
    assert resp.status_code == 403


def test_an_admin_may_do_all_of_it(client: TestClient, demo_bank: Any) -> None:
    c = _signed_in(client, demo_bank, "admin")
    assert (
        c.post(
            "/admin/api/demo/documents",
            json={"title": "Fees", "content": "A fee schedule.", "language": "en"},
        ).status_code
        == 201
    )
    assert c.post("/admin/api/demo/handoff-webhook", json={"url": None}).status_code == 200


def test_being_refused_a_permission_is_403_not_401(
    client: TestClient, demo_bank: Any
) -> None:
    """They are signed in. The answer is "not you", not "who are you".

    Collapsing the two would bounce a legitimate operator to the login screen,
    where they would sign in again successfully and be bounced again.
    """
    c = _signed_in(client, demo_bank, "operator")
    assert c.post("/admin/api/demo/handoff-webhook", json={"url": None}).status_code == 403

    anonymous = TestClient(client.app)
    assert (
        anonymous.post(
            "/admin/api/demo/handoff-webhook", json={"url": None}
        ).status_code
        == 401
    )


def test_a_session_for_one_bank_cannot_act_on_another(
    client: TestClient, demo_bank: Any, second_bank: Any
) -> None:
    """Without this the per-tenant model is decoration.

    An administrator at one bank is a stranger at every other, no matter how
    privileged their own role.
    """
    c = _signed_in(client, demo_bank, "admin")
    assert c.get("/admin/api/other/handoffs").status_code == 403
    assert c.get("/admin/api/other/documents").status_code == 403


def test_a_disabled_user_loses_access_they_already_hold(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    c = _signed_in(client, demo_bank, "admin")
    assert c.get("/admin/api/demo/handoffs").status_code == 200

    user = db_session.execute(
        select(User).where(User.email == "admin@bank.et")
    ).scalar_one()
    from datetime import UTC, datetime

    user.disabled_at = datetime.now(UTC)
    db_session.commit()

    assert c.get("/admin/api/demo/handoffs").status_code == 401


# ------------------------------------------------------- the break-glass token


def test_the_token_still_reaches_everything(
    client: TestClient, demo_bank: Any
) -> None:
    """It is recovery and automation. Narrowing it would strand a tenant."""
    h = _headers(demo_bank)
    assert client.get("/admin/api/demo/handoffs", headers=h).status_code == 200
    assert (
        client.post(
            "/admin/api/demo/documents",
            headers=h,
            json={"title": "T", "content": "C", "language": "en"},
        ).status_code
        == 201
    )


def test_the_token_audits_as_itself_not_as_a_person(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """An audit trail that invents an actor is worse than one that admits it can't."""
    client.post(
        "/admin/api/demo/documents",
        headers=_headers(demo_bank),
        json={"title": "T", "content": "C", "language": "en"},
    )
    entry = db_session.execute(
        select(AuditLog).where(AuditLog.action == "document_created")
    ).scalars().first()
    assert entry is not None
    assert entry.actor == "admin-token"


def test_a_persons_action_is_audited_against_them(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """The point of the whole change: the log stops saying "admin" for everyone."""
    c = _signed_in(client, demo_bank, "admin")
    c.post(
        "/admin/api/demo/documents",
        json={"title": "T", "content": "C", "language": "en"},
    )
    user = db_session.execute(
        select(User).where(User.email == "admin@bank.et")
    ).scalar_one()
    entry = db_session.execute(
        select(AuditLog).where(AuditLog.action == "document_created")
    ).scalars().first()
    assert entry is not None
    assert entry.actor == user.id
    assert entry.actor != "admin"


def test_closing_a_handoff_records_who_and_stays_null_for_the_token(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Null is a true statement about a tenant-wide token. "admin" would not be."""
    c = _signed_in(client, demo_bank, "admin")
    user = db_session.execute(
        select(User).where(User.email == "admin@bank.et")
    ).scalar_one()

    by_person = Handoff(bank_id=demo_bank.id, conversation_id="c1", reason="other")
    by_token = Handoff(bank_id=demo_bank.id, conversation_id="c2", reason="other")
    db_session.add_all([by_person, by_token])
    db_session.commit()

    assert c.post(f"/admin/api/demo/handoffs/{by_person.id}/close").status_code == 200
    assert (
        client.post(
            f"/admin/api/demo/handoffs/{by_token.id}/close",
            headers=_headers(demo_bank),
        ).status_code
        == 200
    )
    db_session.expire_all()
    assert db_session.get(Handoff, by_person.id).resolved_by == user.id  # type: ignore[union-attr]
    assert db_session.get(Handoff, by_token.id).resolved_by is None  # type: ignore[union-attr]


# --------------------------------------------------- the policy cannot drift


def _guarded_admin_routes() -> list[Any]:
    """Admin API routes that are meant to be behind a permission.

    Excludes the identity routes: login and logout must be reachable by
    someone with no session at all, and `me`/`me/password` are about yourself
    rather than about a capability.
    """
    unguarded_by_design = {
        "/admin/api/{slug}/login",
        "/admin/api/{slug}/logout",
        "/admin/api/{slug}/me",
        "/admin/api/{slug}/me/password",
    }
    return [
        r
        for r in app.routes
        if getattr(r, "path", "").startswith("/admin/api/")
        and getattr(r, "path", "") not in unguarded_by_design
    ]


def test_every_admin_route_declares_a_permission() -> None:
    """Read off the live route table, not off a list someone maintains.

    This is the test that catches the realistic mistake: a route added in six
    months with no guard at all. Every other test in this file passes happily
    while that route is wide open, because none of them know it exists.
    """
    # api.py uses `from __future__ import annotations`, so every annotation is
    # a STRING at runtime. Comparing against the class silently matched nothing
    # and the first run of this test reported all fifteen routes as unguarded —
    # a false alarm, but the informative kind: it proves the check is actually
    # reading the route table rather than asserting something vacuous.
    unguarded = []
    for route in _guarded_admin_routes():
        endpoint = getattr(route, "endpoint", None)
        hints = getattr(endpoint, "__annotations__", {})
        if hints.get("principal") not in ("Principal", Principal):
            unguarded.append(f"{sorted(route.methods)} {route.path}")
    assert not unguarded, (
        "these admin routes take no Principal, so nothing checked a permission: "
        + ", ".join(unguarded)
    )


def test_no_route_guards_a_permission_the_registry_never_defined() -> None:
    """A typo'd permission string would guard a route against everyone.

    `require("documnets.write")` is in no role, so the route silently becomes
    reachable only by the break-glass token — a lockout that looks like a
    permissions problem and would be debugged as one.
    """
    from bankassist import api

    declared = {
        getattr(api, name).dependency.__closure__[0].cell_contents  # type: ignore[union-attr]
        for name in dir(api)
        if name.startswith("Needs")
    }
    unknown = declared - set(permissions.ALL)
    assert not unknown, f"routes guard permissions that do not exist: {unknown}"


@pytest.mark.parametrize("permission", permissions.ALL)
def test_every_permission_is_held_by_at_least_one_builtin_role(
    permission: str,
) -> None:
    """A permission in no role can only ever be exercised by the shared token."""
    holders = [
        name
        for name, perms in permissions.BUILTIN_ROLES.items()
        if permission in perms
    ]
    assert holders, f"{permission} is unreachable for every signed-in person"
