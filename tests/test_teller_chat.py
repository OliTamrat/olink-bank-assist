"""Text chat during a live teller session.

The two properties that matter: a teller's words are never filed as the
assistant's, and the assistant never answers over the top of a human.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import passwords, permissions, teller
from bankassist.models import Message, Role, User, UserCredential


@pytest.fixture(autouse=True)
def _livekit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://test.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APItest")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s" * 32)


def _staff(
    client: TestClient, db_session: Any, bank: Any, email: str, role_name: str
) -> User:
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
    assert client.post(
        f"/admin/api/{bank.slug}/login",
        json={"email": email, "password": "CorrectHorse9!x"},
    ).status_code == 200
    return user


def _live(client: TestClient, db_session: Any, bank: Any) -> str:
    """A session with a teller already on it."""
    cid = client.post("/chat/demo", json={"message": "Hello"}).json()["conversation_id"]
    sid: str = client.post(
        "/chat/demo/teller-session", json={"conversation_id": cid}
    ).json()["id"]
    _staff(client, db_session, bank, "t@bank.et", permissions.TELLER)
    assert client.post(
        f"/admin/api/demo/teller/sessions/{sid}/claim"
    ).status_code == 200
    return sid


# ------------------------------------------------------------- the record


def test_a_tellers_message_is_never_filed_as_the_assistant(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The assistant's promise to a bank is that everything under its name
    came from the bank's own indexed content. A human's typing stored under
    that role would be indistinguishable from it afterwards — in the
    transcript, in the analytics, and in any audit of what the bot said.
    """
    sid = _live(client, db_session, demo_bank)
    assert client.post(
        f"/admin/api/demo/teller/sessions/{sid}/messages",
        json={"text": "I can see the charge, one moment."},
    ).status_code == 201

    roles = [
        m.role for m in db_session.execute(select(Message)).scalars().all()
        if m.text.startswith("I can see the charge")
    ]
    assert roles == [teller.MESSAGE_ROLE]
    assert teller.MESSAGE_ROLE != "assistant"


def test_a_tellers_message_does_not_count_as_an_assistant_turn(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """If a teller's line counted as an assistant turn, every metric a bank is
    asked to trust would drift the moment tier 3 is used — and it would drift
    in the flattering direction.

    Asserted against `role == "assistant"` directly rather than through the
    analytics endpoint, because a teller does not hold `analytics.read` and
    signing in as somebody who does would swap the cookie mid-test. That
    predicate is exactly what the analytics queries filter on (api.py), so
    this is the property those numbers rest on, not a proxy for it.
    """
    sid = _live(client, db_session, demo_bank)

    def assistant_turns() -> int:
        db_session.expire_all()
        return len([
            m for m in db_session.execute(select(Message)).scalars().all()
            if m.role == "assistant"
        ])

    before = assistant_turns()
    assert client.post(
        f"/admin/api/demo/teller/sessions/{sid}/messages", json={"text": "Hello there"}
    ).status_code == 201
    assert assistant_turns() == before


# ------------------------------------------------- the assistant stays out


def test_the_assistant_does_not_answer_during_a_call(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The single worst thing this feature could do is have a bot reply over
    the top of a human who is mid-sentence. The customer's in-call route has
    no path to the agent at all — this asserts the effect: one message in,
    one message stored, no reply.
    """
    sid = _live(client, db_session, demo_bank)
    before = len(client.get(f"/chat/demo/teller-session/{sid}/messages").json())

    resp = client.post(
        f"/chat/demo/teller-session/{sid}/messages",
        json={"text": "How do I open an account?"},
    )
    assert resp.status_code == 201, resp.text

    after = client.get(f"/chat/demo/teller-session/{sid}/messages").json()
    assert len(after) == before + 1
    assert after[-1]["role"] == "user"


# ------------------------------------------------------------- the thread


def test_the_thread_carries_what_was_said_before_the_call(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The customer explained their problem to the assistant before asking
    for a person. A panel that starts blank makes them explain it twice —
    which is the experience this product exists to replace."""
    sid = _live(client, db_session, demo_bank)
    rows = client.get(f"/chat/demo/teller-session/{sid}/messages").json()
    assert [r["role"] for r in rows][:2] == ["user", "assistant"]

    staff = client.get(f"/admin/api/demo/teller/sessions/{sid}/messages").json()
    assert [r["text"] for r in staff] == [r["text"] for r in rows]


def test_both_sides_see_the_same_thread_in_the_same_order(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _live(client, db_session, demo_bank)
    client.post(
        f"/admin/api/demo/teller/sessions/{sid}/messages", json={"text": "What is the reference?"}
    )
    client.post(
        f"/chat/demo/teller-session/{sid}/messages", json={"text": "TX-99120"}
    )
    customer = client.get(f"/chat/demo/teller-session/{sid}/messages").json()
    staff = client.get(f"/admin/api/demo/teller/sessions/{sid}/messages").json()
    assert [(r["role"], r["text"]) for r in customer] == [
        (r["role"], r["text"]) for r in staff
    ]
    assert [r["role"] for r in customer][-2:] == [teller.MESSAGE_ROLE, "user"]


# ------------------------------------------------------------- the limits


def test_only_the_teller_on_the_session_can_write_to_it(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Another teller holding teller.serve is not in this conversation."""
    sid = _live(client, db_session, demo_bank)
    _staff(client, db_session, demo_bank, "other@bank.et", permissions.TELLER)
    resp = client.post(
        f"/admin/api/demo/teller/sessions/{sid}/messages", json={"text": "hello"}
    )
    assert resp.status_code == 403, resp.text


def test_another_teller_cannot_read_the_thread_either(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _live(client, db_session, demo_bank)
    _staff(client, db_session, demo_bank, "other@bank.et", permissions.TELLER)
    assert client.get(
        f"/admin/api/demo/teller/sessions/{sid}/messages"
    ).status_code == 403


def test_nobody_writes_to_a_session_that_is_not_live(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A queued session has no teller to read it; an ended one is a closed
    record. Appending to either would put a message somewhere nobody looks."""
    sid = _live(client, db_session, demo_bank)
    client.post(f"/admin/api/demo/teller/sessions/{sid}/end", json={})
    assert client.post(
        f"/chat/demo/teller-session/{sid}/messages", json={"text": "hello?"}
    ).status_code == 409
    assert client.post(
        f"/admin/api/demo/teller/sessions/{sid}/messages", json={"text": "hello?"}
    ).status_code == 409


def test_a_session_from_another_bank_is_not_writable(
    client: TestClient, demo_bank: Any, cbe_bank: Any, db_session: Any
) -> None:
    sid = _live(client, db_session, demo_bank)
    assert client.post(
        f"/chat/cbe/teller-session/{sid}/messages", json={"text": "hello"}
    ).status_code == 404


def test_an_empty_message_is_refused(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _live(client, db_session, demo_bank)
    for body in ({"text": ""}, {"text": "   "}):
        resp = client.post(f"/chat/demo/teller-session/{sid}/messages", json=body)
        assert resp.status_code == 422, resp.text
