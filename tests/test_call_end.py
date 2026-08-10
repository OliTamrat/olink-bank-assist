"""When a call ends, both screens have to find out.

Reported from the field: the customer hung up, and the teller's dashboard
stayed in the call — a live session with nobody on the other end of it. It
would still have been there the next morning, sitting in the In-progress list
above the people actually waiting.

Two independent faults, and fixing either alone leaves the bug:

1. The widget disconnected from the media layer and told the SERVER nothing,
   so the row stayed ACTIVE forever.
2. The teller's screen only learned about departures from LiveKit's
   participant-left event, which is best-effort. A phone that loses signal,
   gets backgrounded, or is switched off produces no clean disconnect.

So the customer now says they are leaving, and the teller's open call room
asks the database rather than waiting to be told.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import permissions, teller
from bankassist.models import AuditLog, TellerSession


def _conversation(client: TestClient, slug: str = "demo") -> str:
    resp = client.post(f"/chat/{slug}", json={"message": "Hello"})
    assert resp.status_code == 200, resp.text
    cid: str = resp.json()["conversation_id"]
    return cid


def _staff(client: TestClient, db_session: Any, bank: Any, email: str,
           display: str = "Meron Tesfaye") -> Any:
    from bankassist import passwords
    from bankassist.models import Role, User, UserCredential

    role = db_session.execute(
        select(Role).where(Role.bank_id == bank.id, Role.name == permissions.TELLER)
    ).scalar_one()
    user = User(bank_id=bank.id, email=email, display_name=display, role_id=role.id)
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserCredential(
            user_id=user.id, kind="password",
            secret_hash=passwords.hash_password("CorrectHorse9!x"),
        )
    )
    db_session.commit()
    assert client.post(
        f"/admin/api/{bank.slug}/login",
        json={"email": email, "password": "CorrectHorse9!x"},
    ).status_code == 200
    return user


def _claimed(client: TestClient, db_session: Any, bank: Any,
             email: str = "t@bank.et", display: str = "Meron Tesfaye") -> str:
    sid: str = client.post(
        f"/chat/{bank.slug}/teller-session",
        json={"conversation_id": _conversation(client, bank.slug)},
    ).json()["id"]
    _staff(client, db_session, bank, email, display)
    assert client.post(
        f"/admin/api/{bank.slug}/teller/sessions/{sid}/claim"
    ).status_code == 200
    return sid


def test_a_customer_hanging_up_ends_the_session(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The regression. Before this, the row stayed ACTIVE forever."""
    sid = _claimed(client, db_session, demo_bank)
    client.cookies.clear()          # the customer is not signed in

    resp = client.delete(f"/chat/demo/teller-session/{sid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == teller.ENDED

    db_session.expire_all()
    assert db_session.get(TellerSession, sid).state == teller.ENDED


def test_hanging_up_is_recorded_differently_from_giving_up_in_the_queue(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """One action for the customer, two different facts for the bank. A bank
    reading its own audit trail must be able to tell "the call happened and
    they hung up" from "they never got through" — the second is a staffing
    number, the first is not."""
    waiting = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()["id"]
    client.delete(f"/chat/demo/teller-session/{waiting}")

    called = _claimed(client, db_session, demo_bank)
    client.cookies.clear()
    client.delete(f"/chat/demo/teller-session/{called}")

    actions = {
        row.entity_id: row.action
        for row in db_session.execute(
            select(AuditLog).where(AuditLog.action.like("teller_session_%"))
        ).scalars().all()
        if row.action in ("teller_session_abandoned", "teller_session_customer_hung_up")
    }
    assert actions[waiting] == "teller_session_abandoned"
    assert actions[called] == "teller_session_customer_hung_up"


def test_leaving_twice_is_not_an_error(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A hang-up and a closing tab both fire this, in that order, and the
    second must not surface an error in the customer's browser."""
    sid = _claimed(client, db_session, demo_bank)
    client.cookies.clear()
    assert client.delete(f"/chat/demo/teller-session/{sid}").status_code == 200
    second = client.delete(f"/chat/demo/teller-session/{sid}")
    assert second.status_code == 200
    assert second.json()["state"] == teller.ENDED


def test_the_teller_can_read_a_session_that_has_just_ended(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The route the open call room polls, and the reason it is not
    `_live_session`: a endpoint that 409s the moment the call ends cannot be
    the one that tells the teller it ended."""
    sid = _claimed(client, db_session, demo_bank)
    cookies = dict(client.cookies)

    client.cookies.clear()
    client.delete(f"/chat/demo/teller-session/{sid}")

    for name, value in cookies.items():
        client.cookies.set(name, value)
    resp = client.get(f"/admin/api/demo/teller/sessions/{sid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == teller.ENDED


def test_another_teller_cannot_read_someone_elses_session(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A finished session is still a record of a named customer's business."""
    sid = _claimed(client, db_session, demo_bank, "first@bank.et")
    _staff(client, db_session, demo_bank, "second@bank.et", "Abel Kebede")
    assert client.get(
        f"/admin/api/demo/teller/sessions/{sid}"
    ).status_code == 403


# --------------------------------------------------------- who is on the call


def test_the_customer_is_told_the_tellers_first_name(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Reported from the field: the teller's screen named the customer while
    the customer's screen said only "teller". A voice with no name is a call
    centre; a first name is a person who is accountable for what they say."""
    sid = _claimed(client, db_session, demo_bank, display="Meron Tesfaye")
    client.cookies.clear()

    body = client.get(f"/chat/demo/teller-session/{sid}").json()
    assert body["teller_name"] == "Meron"


def test_the_customer_is_never_told_the_surname(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The half that is not a nicety. A surname turns an ordinary support call
    into a person who can be looked up, turned up at, or impersonated to a
    colleague — and bank staff take calls from people who are angry about
    money. The trust is in the first name; the risk is all in the rest."""
    sid = _claimed(client, db_session, demo_bank, display="Meron Tesfaye")
    client.cookies.clear()

    body = client.get(f"/chat/demo/teller-session/{sid}").text
    assert "Tesfaye" not in body


def test_nobody_is_named_before_the_session_is_claimed(
    client: TestClient, demo_bank: Any
) -> None:
    """Null, not a placeholder. Naming somebody who has not picked up would be
    a promise the queue cannot keep."""
    sid = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()["id"]
    assert client.get(f"/chat/demo/teller-session/{sid}").json()["teller_name"] is None


def test_an_account_with_no_display_name_falls_back_rather_than_showing_a_gap(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Accounts get created with an email and nothing else. The customer's
    screen then reads "Demo Bank Ethiopia teller", which is the old behaviour
    and fine — an empty space where a name should be is not."""
    from bankassist.api import first_name

    sid = _claimed(client, db_session, demo_bank, display="")
    client.cookies.clear()
    assert client.get(f"/chat/demo/teller-session/{sid}").json()["teller_name"] is None
    assert first_name(None) is None
    assert first_name("   ") is None
    assert first_name("Meron") == "Meron"
