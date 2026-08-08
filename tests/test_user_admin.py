"""Managing colleagues: listing, disabling, restoring, and the role table."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import permissions
from bankassist.models import AdminSession, User

_FIXTURE = "pytest-fixture-value"
PW = f"{_FIXTURE}-original"


def _headers(bank: Any) -> dict[str, str]:
    return {"X-Admin-Token": bank.admin_token}


def _make_user(
    client: TestClient, bank: Any, email: str, role: str = "operator"
) -> dict[str, Any]:
    resp = client.post(
        "/admin/api/demo/users",
        headers=_headers(bank),
        json={"email": email, "password": PW, "role": role},
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _signed_in(client: TestClient, bank: Any, email: str, role: str) -> TestClient:
    _make_user(client, bank, email, role)
    c = TestClient(client.app)
    assert c.post(
        "/admin/api/demo/login", json={"email": email, "password": PW}
    ).status_code == 200
    return c


def test_the_list_includes_disabled_people(
    client: TestClient, demo_bank: Any
) -> None:
    """"Who can get in here" is the question this screen answers.

    An answer that silently omits removed accounts is the wrong answer: an
    access review needs to see that someone was removed, not find no trace.
    """
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    gone = _make_user(client, demo_bank, "leaver@bank.et")
    admin.post(f"/admin/api/demo/users/{gone['id']}/active", json={"is_active": False})

    rows = admin.get("/admin/api/demo/users").json()
    by_email = {r["email"]: r for r in rows}
    assert "leaver@bank.et" in by_email
    assert by_email["leaver@bank.et"]["is_active"] is False
    assert by_email["boss@bank.et"]["is_active"] is True


def test_the_list_marks_which_row_is_you(
    client: TestClient, demo_bank: Any
) -> None:
    """So the UI can grey out an action that would always be refused."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    _make_user(client, demo_bank, "someone@bank.et")
    rows = {r["email"]: r for r in admin.get("/admin/api/demo/users").json()}
    assert rows["boss@bank.et"]["is_you"] is True
    assert rows["someone@bank.et"]["is_you"] is False


def test_disabling_someone_ends_their_sessions_immediately(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Removing someone is the whole feature. A delay would be theatre."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    victim = _signed_in(client, demo_bank, "ops@bank.et", "operator")
    assert victim.get("/admin/api/demo/handoffs").status_code == 200

    target = db_session.execute(
        select(User).where(User.email == "ops@bank.et")
    ).scalar_one()
    resp = admin.post(
        f"/admin/api/demo/users/{target.id}/active", json={"is_active": False}
    )
    assert resp.status_code == 200
    assert resp.json()["sessions_revoked"] == 1

    assert victim.get("/admin/api/demo/handoffs").status_code == 401
    live = db_session.execute(
        select(AdminSession).where(
            AdminSession.user_id == target.id, AdminSession.revoked_at.is_(None)
        )
    ).scalars().all()
    assert live == []


def test_restoring_someone_lets_them_sign_in_again(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Disabled is not deleted — the row survives so audit entries resolve."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    back = _make_user(client, demo_bank, "returner@bank.et")
    admin.post(f"/admin/api/demo/users/{back['id']}/active", json={"is_active": False})

    fresh = TestClient(client.app)
    assert fresh.post(
        "/admin/api/demo/login", json={"email": "returner@bank.et", "password": PW}
    ).status_code == 401

    admin.post(f"/admin/api/demo/users/{back['id']}/active", json={"is_active": True})
    assert fresh.post(
        "/admin/api/demo/login", json={"email": "returner@bank.et", "password": PW}
    ).status_code == 200


def test_you_cannot_disable_yourself(client: TestClient, demo_bank: Any) -> None:
    """The realistic mistake is the only admin locking themselves out mid-task."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    me = admin.get("/admin/api/demo/users").json()
    mine = next(r for r in me if r["is_you"])
    resp = admin.post(
        f"/admin/api/demo/users/{mine['id']}/active", json={"is_active": False}
    )
    assert resp.status_code == 409
    assert admin.get("/admin/api/demo/handoffs").status_code == 200


def test_a_user_from_another_bank_is_not_found_here(
    client: TestClient, demo_bank: Any, second_bank: Any, db_session: Session
) -> None:
    """A raw id must not be a way around the tenant boundary."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    stranger = User(bank_id=second_bank.id, email="x@other.et", role_id="irrelevant")
    # Inserted directly: the API cannot create a user for a bank you are not in,
    # which is the point — this checks the lookup, not the creation path.
    db_session.add(stranger)
    db_session.flush()
    resp = admin.post(
        f"/admin/api/demo/users/{stranger.id}/active", json={"is_active": False}
    )
    assert resp.status_code == 404


def test_an_operator_cannot_see_or_change_the_team(
    client: TestClient, demo_bank: Any
) -> None:
    ops = _signed_in(client, demo_bank, "ops@bank.et", "operator")
    assert ops.get("/admin/api/demo/users").status_code == 403
    assert ops.get("/admin/api/demo/roles").status_code == 403


def test_the_role_table_is_generated_from_what_is_enforced(
    client: TestClient, demo_bank: Any
) -> None:
    """Not a hand-written help page.

    It reads the same rows `require()` checks, so it cannot describe a policy
    the system is not actually applying — which is the failure mode of every
    permissions matrix kept in a document.
    """
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    rows = {r["name"]: r for r in admin.get("/admin/api/demo/roles").json()}
    assert set(rows) == {"operator", "admin"}
    assert set(rows["admin"]["permissions"]) == set(permissions.ALL)
    assert permissions.Perm.DOCUMENTS_WRITE not in rows["operator"]["permissions"]
    assert rows["operator"]["is_builtin"] is True


def test_integration_settings_show_state_but_never_secrets(
    client: TestClient, demo_bank: Any
) -> None:
    """The screen must show what is wired up, and nothing that could forge it.

    The settings page shipped with empty fields whether or not anything was
    connected. That is worse than unhelpful on this particular page: the one
    control on it decides where customers' names and phone numbers are
    delivered, and someone who cannot see the current value can disconnect it
    by saving a field they believed was already blank.
    """
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")

    before = admin.get("/admin/api/demo/integrations").json()
    assert before["handoff_webhook"]["connected"] is False
    assert before["handoff_webhook"]["url"] is None

    created = admin.post(
        "/admin/api/demo/handoff-webhook",
        json={"url": "https://contact-centre.example/hooks/olink"},
    ).json()
    secret = created["secret"]

    after = admin.get("/admin/api/demo/integrations")
    body = after.json()
    assert body["handoff_webhook"]["connected"] is True
    assert body["handoff_webhook"]["url"] == "https://contact-centre.example/hooks/olink"
    assert body["handoff_webhook"]["has_secret"] is True
    # The signing secret is issued once and never readable again — a value the
    # API will re-display is a value that ends up in a screenshot.
    assert secret not in after.text


def test_an_operator_cannot_read_the_integration_settings(
    client: TestClient, demo_bank: Any
) -> None:
    """It names where customer contact details are sent."""
    ops = _signed_in(client, demo_bank, "ops@bank.et", "operator")
    assert ops.get("/admin/api/demo/integrations").status_code == 403
