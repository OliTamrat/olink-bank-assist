"""Expertise routing — which desks a teller knows, and what that may change.

The rules mirror language routing exactly, and these tests hold the mirror:
undeclared means everything (or every queue empties the day it ships),
routing reorders and never hides, language outranks expertise (a
conversation you cannot hold is worse than a desk you know less well), and
past PATIENCE no match of either kind outranks the wait. Plus the endpoint
rules: self-only, strict desk validation, canonical storage order — and the
session's own department classified from the customer's words at request
time.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import departments, passwords, permissions
from bankassist import teller as t
from bankassist.models import Role, TellerSession, User, UserCredential

AM, EN = "am", "en"
CARDS, LENDING, FRAUD = departments.CARDS, departments.LENDING, departments.FRAUD


@pytest.fixture(autouse=True)
def _livekit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://test.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APItest")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s" * 32)


# ------------------------------------------------------------------ covers


def test_an_undeclared_teller_covers_every_desk() -> None:
    assert t.covers(None, CARDS) is True
    assert t.covers([], CARDS) is True


def test_a_declared_teller_matches_their_own_desks() -> None:
    assert t.covers([CARDS, FRAUD], CARDS) is True
    assert t.covers([CARDS, FRAUD], LENDING) is False


def test_a_session_with_no_department_matches_anybody() -> None:
    assert t.covers([CARDS], None) is True


# ------------------------------------------------------------------- order


def test_expertise_orders_within_a_language_group() -> None:
    # Same language, the lending question waited longer — but this teller
    # works cards, so the cards question is offered first.
    order = t.queue_order(
        [(AM, LENDING, 40), (AM, CARDS, 10)], [AM], [CARDS]
    )
    assert order == [1, 0]


def test_language_outranks_expertise() -> None:
    """A desk match must never beat a language match: a conversation the
    teller cannot hold at all is worse than a desk they know less well."""
    order = t.queue_order(
        [(EN, CARDS, 30), (AM, LENDING, 10)], [AM], [CARDS]
    )
    assert order == [1, 0]


def test_oldest_first_still_holds_inside_a_matched_group() -> None:
    order = t.queue_order(
        [(AM, CARDS, 10), (AM, CARDS, 50)], [AM], [CARDS]
    )
    assert order == [1, 0]


def test_nobody_is_starved_by_a_desk_they_do_not_cover() -> None:
    long_wait = t.PATIENCE + 1
    order = t.queue_order(
        [(AM, CARDS, 5), (AM, LENDING, long_wait)], [AM], [CARDS]
    )
    assert order[0] == 1


def test_an_undeclared_teller_gets_a_plain_oldest_first_queue() -> None:
    order = t.queue_order(
        [(AM, CARDS, 10), (AM, LENDING, 50)], None, None
    )
    assert order == [1, 0]


# ---------------------------------------------------------- the endpoint


def _teller_client(
    client: TestClient, db_session: Any, bank: Any, email: str
) -> TestClient:
    role = db_session.execute(
        select(Role).where(
            Role.bank_id == bank.id, Role.name == permissions.TELLER
        )
    ).scalar_one()
    user = User(
        bank_id=bank.id, email=email, display_name=email, role_id=role.id
    )
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


def test_a_teller_declares_their_own_desks(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    me = _teller_client(client, db_session, demo_bank, "desk@bank.et")
    resp = me.put(
        "/admin/api/demo/teller/expertise",
        json={"departments": [LENDING, CARDS, CARDS]},
    )
    assert resp.status_code == 200
    # De-duplicated, and in the canonical desk order — cards before lending.
    assert resp.json() == {"departments": [CARDS, LENDING]}

    settings = me.get("/admin/api/demo/teller/settings").json()
    assert settings["departments"] == [CARDS, LENDING]
    assert [d["department"] for d in settings["all_departments"]] == list(
        departments.DEPARTMENTS
    )


def test_an_unknown_desk_is_refused_not_dropped(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    me = _teller_client(client, db_session, demo_bank, "desk2@bank.et")
    resp = me.put(
        "/admin/api/demo/teller/expertise", json={"departments": ["fees"]}
    )
    assert resp.status_code == 422
    assert "fees" in resp.json()["detail"]


def test_an_empty_list_clears_the_declaration(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    me = _teller_client(client, db_session, demo_bank, "desk3@bank.et")
    assert me.put(
        "/admin/api/demo/teller/expertise", json={"departments": [FRAUD]}
    ).status_code == 200
    assert me.put(
        "/admin/api/demo/teller/expertise", json={"departments": []}
    ).status_code == 200
    user = db_session.execute(
        select(User).where(User.email == "desk3@bank.et")
    ).scalar_one()
    db_session.refresh(user)
    assert user.teller_departments is None


def test_the_break_glass_token_cannot_declare_expertise(
    client: TestClient, demo_bank: Any
) -> None:
    """The token is nobody in particular — there is no self to declare for."""
    resp = client.put(
        "/admin/api/demo/teller/expertise",
        headers={"X-Admin-Token": demo_bank.admin_token},
        json={"departments": [CARDS]},
    )
    assert resp.status_code == 403


# -------------------------------------------------- manager assignment


def _admin_client(
    client: TestClient, db_session: Any, bank: Any, email: str
) -> TestClient:
    role = db_session.execute(
        select(Role).where(
            Role.bank_id == bank.id, Role.name == permissions.ADMIN
        )
    ).scalar_one()
    user = User(
        bank_id=bank.id, email=email, display_name=email, role_id=role.id
    )
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


def _user_id(db_session: Any, email: str) -> str:
    user = db_session.execute(
        select(User).where(User.email == email)
    ).scalar_one()
    return str(user.id)


def test_a_manager_assigns_a_team_members_desks(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    _teller_client(client, db_session, demo_bank, "assignee@bank.et")
    manager = _admin_client(client, db_session, demo_bank, "mgr@bank.et")
    uid = _user_id(db_session, "assignee@bank.et")
    resp = manager.put(
        f"/admin/api/demo/users/{uid}/expertise",
        json={"departments": [LENDING, FRAUD, FRAUD]},
    )
    assert resp.status_code == 200
    # Canonical desk order, de-duplicated — same rule as self-declaration.
    assert resp.json() == {"user_id": uid, "departments": [FRAUD, LENDING]}

    user = db_session.execute(
        select(User).where(User.email == "assignee@bank.et")
    ).scalar_one()
    db_session.refresh(user)
    assert user.teller_departments == [FRAUD, LENDING]


def test_the_assignment_is_audited_under_its_own_action(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    from bankassist.models import AuditLog

    _teller_client(client, db_session, demo_bank, "audited@bank.et")
    manager = _admin_client(client, db_session, demo_bank, "mgr2@bank.et")
    uid = _user_id(db_session, "audited@bank.et")
    assert manager.put(
        f"/admin/api/demo/users/{uid}/expertise",
        json={"departments": [CARDS]},
    ).status_code == 200
    row = db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "teller_expertise_assigned",
            AuditLog.entity_id == uid,
        )
    ).scalars().first()
    assert row is not None
    # The actor is the manager, not the person whose desks changed — a
    # disagreement between the two must be visible, not silent.
    assert row.actor == _user_id(db_session, "mgr2@bank.et")


def test_a_manager_cannot_assign_desks_to_a_non_teller(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """A desk assigned to somebody routing can never offer work to would
    make the roster look covered while routing as if it were not."""
    operator_role = db_session.execute(
        select(Role).where(
            Role.bank_id == demo_bank.id, Role.name == permissions.OPERATOR
        )
    ).scalar_one()
    user = User(
        bank_id=demo_bank.id, email="ops@bank.et",
        display_name="ops@bank.et", role_id=operator_role.id,
    )
    db_session.add(user)
    db_session.commit()
    manager = _admin_client(client, db_session, demo_bank, "boss@bank.et")
    resp = manager.put(
        f"/admin/api/demo/users/{user.id}/expertise",
        json={"departments": [CARDS]},
    )
    assert resp.status_code == 409


def test_one_banks_manager_cannot_reach_anothers_roster(
    client: TestClient, db_session: Any, demo_bank: Any, cbe_bank: Any
) -> None:
    _teller_client(client, db_session, cbe_bank, "cbe-teller@bank.et")
    uid = _user_id(db_session, "cbe-teller@bank.et")
    resp = client.put(
        f"/admin/api/demo/users/{uid}/expertise",
        headers={"X-Admin-Token": demo_bank.admin_token},
        json={"departments": [CARDS]},
    )
    assert resp.status_code == 404


def test_a_plain_teller_cannot_assign_a_colleagues_desks(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """users.manage is the gate — the same one the Team page sits behind."""
    _teller_client(client, db_session, demo_bank, "colleague@bank.et")
    me = _teller_client(client, db_session, demo_bank, "plain@bank.et")
    uid = _user_id(db_session, "colleague@bank.et")
    resp = me.put(
        f"/admin/api/demo/users/{uid}/expertise",
        json={"departments": [CARDS]},
    )
    assert resp.status_code == 403


# ------------------------------------------- the session's own department


def test_a_session_is_classified_from_the_customers_own_words(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    cid = client.post(
        "/chat/demo", json={"message": "My card was swallowed by the ATM"}
    ).json()["conversation_id"]
    sid = client.post(
        "/chat/demo/teller-session", json={"conversation_id": cid}
    ).json()["id"]
    session = db_session.get(TellerSession, sid)
    db_session.refresh(session)
    assert session.department == CARDS


def test_a_session_with_no_messages_lands_on_general(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """Somebody who taps Connect before typing anything still gets a desk —
    the one that exists so nothing is orphaned."""
    cid = client.post("/chat/demo", json={"message": "hi"}).json()[
        "conversation_id"
    ]
    # A bare greeting carries no desk vocabulary at all.
    sid = client.post(
        "/chat/demo/teller-session", json={"conversation_id": cid}
    ).json()["id"]
    session = db_session.get(TellerSession, sid)
    db_session.refresh(session)
    assert session.department == departments.GENERAL


def test_the_queue_tells_each_teller_what_they_cover(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    cid = client.post(
        "/chat/demo", json={"message": "I need a loan for my business"}
    ).json()["conversation_id"]
    client.post("/chat/demo/teller-session", json={"conversation_id": cid})

    cards_teller = _teller_client(client, db_session, demo_bank, "c@bank.et")
    assert cards_teller.put(
        "/admin/api/demo/teller/expertise", json={"departments": [CARDS]}
    ).status_code == 200
    rows = cards_teller.get("/admin/api/demo/teller/queue").json()
    assert rows[0]["department"] == LENDING
    assert rows[0]["department_label"] == departments.label(LENDING)
    assert rows[0]["covers"] is False

    lending_teller = _teller_client(client, db_session, demo_bank, "l@bank.et")
    assert lending_teller.put(
        "/admin/api/demo/teller/expertise", json={"departments": [LENDING]}
    ).status_code == 200
    rows = lending_teller.get("/admin/api/demo/teller/queue").json()
    assert rows[0]["covers"] is True


def test_the_team_list_says_who_can_actually_serve(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """The Desk Teams view counts only people routing can offer work to —
    by permission, not role name, so a renamed teller role keeps working."""
    _teller_client(client, db_session, demo_bank, "serves@bank.et")
    users = _admin_client(
        client, db_session, demo_bank, "roster-reader@bank.et"
    ).get("/admin/api/demo/users").json()
    by_email = {u["email"]: u for u in users}
    assert by_email["serves@bank.et"]["can_serve"] is True


def test_the_admin_desk_labels_mirror_the_server() -> None:
    """admin.html carries a DESK_LABEL map for payloads that send only desk
    codes. It must be exactly departments.LABELS or the Team page and the
    queue disagree about what a desk is called."""
    import json
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "bankassist" / "static" / "admin.html"
    ).read_text(encoding="utf-8")
    match = re.search(r"var DESK_LABEL = (\{.*?\});", source, re.DOTALL)
    assert match, "DESK_LABEL map missing from admin.html"
    # The literal is JS, not JSON — quote the bare keys before parsing.
    literal = re.sub(r"(\w+):", r'"\1":', match.group(1))
    assert json.loads(literal) == departments.LABELS


def test_the_team_list_shows_each_persons_declared_coverage(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    me = _teller_client(client, db_session, demo_bank, "cover@bank.et")
    assert me.put(
        "/admin/api/demo/teller/expertise", json={"departments": [FRAUD]}
    ).status_code == 200
    assert me.put(
        "/admin/api/demo/teller/languages", json={"languages": ["am"]}
    ).status_code == 200

    users = _admin_client(
        client, db_session, demo_bank, "roster-reader@bank.et"
    ).get("/admin/api/demo/users").json()
    mine = next(u for u in users if u["email"] == "cover@bank.et")
    assert mine["teller_departments"] == [FRAUD]
    assert mine["teller_languages"] == ["am"]
