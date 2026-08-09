"""Join tokens over HTTP: who can get into a live call, and when.

`test_livekit_tokens.py` covers what a token grants. This covers who is handed
one — the half where a mistake puts a stranger, or the wrong employee, into
somebody's banking call.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import livekit, passwords, permissions
from bankassist.models import Role, User, UserCredential


@pytest.fixture(autouse=True)
def _livekit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here needs a configured media layer; one asserts the
    opposite and clears these itself."""
    monkeypatch.setenv("LIVEKIT_URL", "wss://test.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APItest")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s" * 32)


def _conversation(client: TestClient, slug: str = "demo") -> str:
    cid: str = client.post(f"/chat/{slug}", json={"message": "Hello"}).json()[
        "conversation_id"
    ]
    return cid


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


def _session(client: TestClient) -> str:
    sid: str = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()["id"]
    return sid


# ------------------------------------------------------------- the customer


def test_a_customer_gets_a_token_once_a_teller_takes_them(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _session(client)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    assert client.post(
        f"/admin/api/demo/teller/sessions/{sid}/claim"
    ).status_code == 200

    body = client.get(f"/chat/demo/teller-session/{sid}/token").json()
    assert body["url"] == "wss://test.livekit.cloud"
    assert body["room"] == livekit.room_name(sid)
    claims = livekit.decode_unverified(body["token"])
    assert claims["video"]["room"] == livekit.room_name(sid)
    assert claims["video"]["canPublish"] is True


def test_no_token_while_still_in_the_queue(
    client: TestClient, demo_bank: Any
) -> None:
    """Before a teller claims it there is nobody to talk to. A token issued
    then is a live media credential for an empty room, sitting in a browser
    for the whole length of the wait."""
    sid = _session(client)
    resp = client.get(f"/chat/demo/teller-session/{sid}/token")
    assert resp.status_code == 409, resp.text


def test_no_token_after_the_call_ends(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _session(client)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")
    client.post(f"/admin/api/demo/teller/sessions/{sid}/end", json={})
    assert client.get(f"/chat/demo/teller-session/{sid}/token").status_code == 409


def test_a_session_from_another_bank_yields_nothing(
    client: TestClient, demo_bank: Any, cbe_bank: Any, db_session: Any
) -> None:
    sid = _session(client)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")
    assert client.get(f"/chat/cbe/teller-session/{sid}/token").status_code == 404


def test_an_unknown_session_yields_nothing(
    client: TestClient, demo_bank: Any
) -> None:
    assert client.get(
        "/chat/demo/teller-session/00000000-0000-0000-0000-000000000000/token"
    ).status_code == 404


# --------------------------------------------------------------- the teller


def test_the_teller_who_took_the_session_can_join(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _session(client)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")

    body = client.get(f"/admin/api/demo/teller/sessions/{sid}/token").json()
    assert body["room"] == livekit.room_name(sid)
    assert body["identity"].startswith("teller-")


def test_another_teller_cannot_drop_into_a_live_call(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The control this endpoint exists for.

    Holding `teller.serve` is permission to work the queue, not permission to
    join any call in the bank. Without this check every teller could sit in on
    any customer's session — a privacy failure that leaves no trace and is
    impossible to explain to a regulator afterwards. Taking over means
    claiming the session, which is audited.
    """
    sid = _session(client)
    _staff(client, db_session, demo_bank, "first@bank.et", permissions.TELLER)
    client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")

    _staff(client, db_session, demo_bank, "second@bank.et", permissions.TELLER)
    resp = client.get(f"/admin/api/demo/teller/sessions/{sid}/token")
    assert resp.status_code == 403, resp.text


def test_an_operator_cannot_join_a_call(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Operators deliberately hold neither sessions.read nor teller.serve —
    working a queue after the fact and appearing live as the bank are
    different jobs."""
    sid = _session(client)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")

    _staff(client, db_session, demo_bank, "op@bank.et", permissions.OPERATOR)
    assert client.get(
        f"/admin/api/demo/teller/sessions/{sid}/token"
    ).status_code == 403


def test_the_break_glass_token_cannot_join_a_call(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A live customer call must be answerable to a named employee, and the
    shared admin token has no person behind it."""
    sid = _session(client)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")
    client.cookies.clear()

    resp = client.get(
        f"/admin/api/demo/teller/sessions/{sid}/token",
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    assert resp.status_code == 403, resp.text


def test_the_teller_route_needs_authentication(
    client: TestClient, demo_bank: Any
) -> None:
    assert client.get(
        "/admin/api/demo/teller/sessions/whatever/token"
    ).status_code == 401


# --------------------------------------------------- the two are in one room


def test_both_parties_land_in_the_same_room(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The whole point. Two tokens, one room, and distinct identities —
    LiveKit treats identity as unique per room, so a collision would have one
    party silently evict the other."""
    sid = _session(client)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")

    staff = client.get(f"/admin/api/demo/teller/sessions/{sid}/token").json()
    customer = client.get(f"/chat/demo/teller-session/{sid}/token").json()

    assert staff["room"] == customer["room"]
    assert staff["identity"] != customer["identity"]


# ------------------------------------------------------------ configuration


def test_a_deployment_without_video_says_so(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """503, not a 500 from deep inside token minting."""
    sid = _session(client)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")
    for var in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(var, raising=False)

    assert client.get(f"/chat/demo/teller-session/{sid}/token").status_code == 503
    assert client.get(
        f"/admin/api/demo/teller/sessions/{sid}/token"
    ).status_code == 503


def test_a_deployment_without_video_does_not_offer_a_call(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same reasoning as presence: offering a call that cannot physically
    connect is worse than no button. Guards the case where a bank switches the
    feature on before LIVEKIT_* is set."""
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    assert client.post(
        "/admin/api/demo/teller/presence", json={"on_duty": True}
    ).status_code == 200
    assert client.get("/banks/demo/public").json()["teller_available"] is True

    for var in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    assert client.get("/banks/demo/public").json()["teller_available"] is False


def test_the_session_state_is_checked_before_the_media_layer(
    client: TestClient, demo_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued session must read as "no teller yet" rather than "video is
    down" — otherwise a missing environment variable and an ordinary wait
    produce the same message and neither can be diagnosed."""
    sid = _session(client)
    for var in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    assert client.get(f"/chat/demo/teller-session/{sid}/token").status_code == 409
