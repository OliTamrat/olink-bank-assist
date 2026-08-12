"""Calls handled, per teller — and who is allowed to see whose.

Manager-only for now, by decision: a person holding `users.manage` sees every
teller's row; a plain teller (`sessions.read` only) sees exactly one row,
their own. The scoping has to hold at the endpoint, not just in what the
admin panel chooses to render — these tests hit the endpoint directly as each
identity and check what actually comes back.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import passwords, permissions
from bankassist.models import Role, User, UserCredential


@pytest.fixture(autouse=True)
def _livekit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://test.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APItest")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s" * 32)


def _staff(
    client: TestClient, db_session: Any, bank: Any, email: str, role_name: str
) -> TestClient:
    """A SEPARATE client signed in as a new person with this role.

    Separate rather than reusing `client`, the same way test_permissions.py
    does it: the cookie jar is per-client, so signing a second person in on
    the shared fixture would leave every later call under this test carrying
    the wrong identity.
    """
    role = db_session.execute(
        select(Role).where(Role.bank_id == bank.id, Role.name == role_name)
    ).scalar_one()
    user = User(bank_id=bank.id, email=email, display_name=email, role_id=role.id)
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserCredential(
            user_id=user.id, kind="password",
            secret_hash=passwords.hash_password("CorrectHorse9!x"),
        )
    )
    db_session.commit()
    session_client = TestClient(client.app)
    resp = session_client.post(
        f"/admin/api/{bank.slug}/login",
        json={"email": email, "password": "CorrectHorse9!x"},
    )
    assert resp.status_code == 200, resp.text
    return session_client


def _claimed_session(client: TestClient, teller_client: TestClient, *, end: bool = False) -> str:
    """A session claimed by `teller_client`, optionally ended too."""
    cid = client.post("/chat/demo", json={"message": "Hello"}).json()["conversation_id"]
    sid: str = client.post(
        "/chat/demo/teller-session", json={"conversation_id": cid}
    ).json()["id"]
    assert teller_client.post(
        f"/admin/api/demo/teller/sessions/{sid}/claim"
    ).status_code == 200
    if end:
        assert teller_client.post(
            f"/admin/api/demo/teller/sessions/{sid}/end", json={"resolution": "done"}
        ).status_code == 200
    return sid


def _performance(caller: TestClient) -> dict[str, Any]:
    resp = caller.get("/admin/api/demo/teller-performance")
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def test_a_manager_sees_every_tellers_row(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    ana = _staff(client, db_session, demo_bank, "ana@bank.et", permissions.TELLER)
    bek = _staff(client, db_session, demo_bank, "bek@bank.et", permissions.TELLER)
    _claimed_session(client, ana, end=True)
    _claimed_session(client, ana, end=True)
    _claimed_session(client, bek, end=True)

    manager = _staff(client, db_session, demo_bank, "mgr@bank.et", permissions.ADMIN)
    data = _performance(manager)
    assert data["is_manager"] is True
    by_id = {row["name"]: row for row in data["tellers"]}
    assert by_id["ana@bank.et"]["count"] == 2
    assert by_id["bek@bank.et"]["count"] == 1
    assert by_id["ana@bank.et"]["states"] == {"ended": 2}


def test_a_teller_with_zero_calls_still_appears_at_zero(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """Same reasoning as the Languages panel showing every supported
    language at zero: a donut listing only who has taken a call reads a
    brand-new teller as "not a teller" rather than "zero calls so far."""
    ana = _staff(client, db_session, demo_bank, "ana5@bank.et", permissions.TELLER)
    _staff(client, db_session, demo_bank, "fresh5@bank.et", permissions.TELLER)
    _claimed_session(client, ana, end=True)

    manager = _staff(client, db_session, demo_bank, "mgr5@bank.et", permissions.ADMIN)
    data = _performance(manager)
    by_id = {row["name"]: row for row in data["tellers"]}
    assert by_id["ana5@bank.et"]["count"] == 1
    assert by_id["fresh5@bank.et"] == {
        "teller_user_id": by_id["fresh5@bank.et"]["teller_user_id"],
        "name": "fresh5@bank.et",
        "count": 0,
        "avg_wait_seconds": 0,
        "states": {},
    }
    # The manager herself holds teller.serve (admin implies every
    # permission) but is not one of "my tellers" for this report — she must
    # not show up as a permanent zero-call row alongside the real ones.
    assert "mgr5@bank.et" not in by_id


def test_a_teller_sees_only_their_own_row_never_a_colleagues(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    ana = _staff(client, db_session, demo_bank, "ana2@bank.et", permissions.TELLER)
    bek = _staff(client, db_session, demo_bank, "bek2@bank.et", permissions.TELLER)
    _claimed_session(client, ana, end=True)
    _claimed_session(client, ana, end=True)
    _claimed_session(client, bek, end=True)
    _claimed_session(client, bek, end=True)
    _claimed_session(client, bek, end=True)

    data = _performance(ana)
    assert data["is_manager"] is False
    assert len(data["tellers"]) == 1
    assert data["tellers"][0]["count"] == 2
    assert data["tellers"][0]["name"] == "ana2@bank.et"
    # Never even mentions the colleague's name or count, at any position.
    names = {row["name"] for row in data["tellers"]}
    assert "bek2@bank.et" not in names


def test_a_teller_with_no_claims_yet_gets_a_zeroed_row_not_an_empty_list(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    fresh = _staff(client, db_session, demo_bank, "fresh@bank.et", permissions.TELLER)
    data = _performance(fresh)
    assert len(data["tellers"]) == 1
    assert data["tellers"][0] == {
        "teller_user_id": data["tellers"][0]["teller_user_id"],
        "name": "fresh@bank.et",
        "count": 0,
        "avg_wait_seconds": 0,
        "states": {},
    }


def test_an_abandoned_session_nobody_claimed_is_not_attributed_to_anyone(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """A queue-staffing signal, not a mark against a teller — see the
    endpoint's own docstring. Left unclaimed, it must not silently inflate
    (or deflate) anyone's count once a teller does show up."""
    ana = _staff(client, db_session, demo_bank, "ana3@bank.et", permissions.TELLER)
    cid = client.post("/chat/demo", json={"message": "Hello"}).json()["conversation_id"]
    client.post("/chat/demo/teller-session", json={"conversation_id": cid})
    # Nobody claims it. ana has claimed nothing either.
    data = _performance(ana)
    assert data["tellers"][0]["count"] == 0


def test_an_operator_cannot_reach_the_endpoint_at_all(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """Operators hold neither `sessions.read` nor `users.manage` by default —
    this is existing route-gating, not a new restriction this feature adds."""
    op = _staff(client, db_session, demo_bank, "op@bank.et", permissions.OPERATOR)
    assert op.get("/admin/api/demo/teller-performance").status_code == 403


def test_one_banks_tellers_never_appear_in_anothers_report(
    client: TestClient, db_session: Any, demo_bank: Any, cbe_bank: Any
) -> None:
    ana = _staff(client, db_session, demo_bank, "ana4@bank.et", permissions.TELLER)
    _claimed_session(client, ana, end=True)

    cbe_mgr = _staff(client, db_session, cbe_bank, "mgr@cbe.et", permissions.ADMIN)
    resp = cbe_mgr.get("/admin/api/cbe/teller-performance")
    assert resp.status_code == 200
    assert resp.json()["tellers"] == []
