"""Viber is the second messaging channel, and the first one whose webhook we
authenticate with a signature rather than a shared secret we chose.

That difference is the whole risk. Telegram hands back a secret we generated
and we compare strings. Viber signs the raw body with the *auth token itself*,
so getting it wrong has two failure modes that both look fine from the
outside: accept everything (anyone can put words in the bank's mouth), or
accept nothing (the channel is simply dead, including Viber's own validation
ping, so it can never be connected at all).

Everything else here is a lesson already paid for on the Telegram route —
disclaimer before the first answer, no reply to a sticker — retested because
a second adapter is exactly where a convention silently stops being followed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import viber

TOKEN = "viber-token-abc123"


def _signed(body: dict[str, Any], token: str = TOKEN) -> tuple[bytes, dict[str, str]]:
    """A body and the header Viber would send with it."""
    raw = json.dumps(body).encode()
    sig = hmac.new(token.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {
        "X-Viber-Content-Signature": sig,
        "Content-Type": "application/json",
    }


@pytest.fixture()
def wired(
    client: TestClient, cbe_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, str, str, str]]:
    """A CBE tenant with Viber connected, and every outbound message captured."""
    from bankassist import api as api_module
    from bankassist.models import Bank

    bank = db_session.get(Bank, cbe_bank.id)
    bank.viber_auth_token = TOKEN
    db_session.commit()

    sent: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        api_module.viber,
        "send_message",
        lambda token, receiver, text, sender: sent.append(
            (token, receiver, text, sender)
        )
        or True,
    )
    return sent


def _say(client: TestClient, text: str, user: str = "u77") -> Any:
    raw, headers = _signed(
        {"event": "message", "message": {"type": "text", "text": text},
         "sender": {"id": user, "name": "A customer"}}
    )
    return client.post("/webhooks/viber/cbe", content=raw, headers=headers)


# --------------------------------------------------------------- signature


def test_an_unsigned_request_is_refused(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """The open-door failure. Without this, anyone who learns the tenant slug
    can make the bank's assistant say things to nobody in particular — and
    worse, can drive real replies to a real customer by naming their id."""
    resp = client.post(
        "/webhooks/viber/cbe",
        content=json.dumps({"event": "message"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 403
    assert wired == []


def test_a_signature_from_the_wrong_token_is_refused(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    raw, headers = _signed(
        {"event": "message", "message": {"text": "hi"}, "sender": {"id": "u1"}},
        token="some-other-token",
    )
    resp = client.post("/webhooks/viber/cbe", content=raw, headers=headers)
    assert resp.status_code == 403
    assert wired == []


def test_a_body_signed_as_sent_verifies_even_when_it_is_not_canonical_json(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """Verification must use the bytes Viber sent, not a re-serialisation.

    This test exists because the obvious wrong implementation —
    `json.dumps(json.loads(raw))` before hashing — survived a mutation of the
    route while every other test here passed. It survived because the helper
    above builds bodies with `json.dumps` too, so the two forms happened to be
    identical and the difference could not show up.

    Real Viber does not send canonically formatted JSON, so the failure would
    have been the honest path breaking in production while the suite stayed
    green. Signing a deliberately non-canonical body — extra whitespace, keys
    out of order — is what makes the distinction visible.
    """
    body = (
        b'{ "event" : "message" ,\n  "sender" : {"id": "u77"},\n'
        b'  "message" : {"text": "hello"} }'
    )
    sig = hmac.new(TOKEN.encode(), body, hashlib.sha256).hexdigest()
    resp = client.post(
        "/webhooks/viber/cbe",
        content=body,
        headers={"X-Viber-Content-Signature": sig,
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert wired, "a validly signed non-canonical body was not answered"


def test_a_signature_for_a_different_body_is_refused(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """A valid signature lifted from one request must not authenticate
    another."""
    _, headers = _signed({"event": "message", "message": {"text": "hi"},
                          "sender": {"id": "u1"}})
    tampered = json.dumps(
        {"event": "message", "message": {"text": "transfer everything"},
         "sender": {"id": "u1"}}
    ).encode()
    resp = client.post("/webhooks/viber/cbe", content=tampered, headers=headers)
    assert resp.status_code == 403
    assert wired == []


def test_a_bank_with_no_token_accepts_nothing(
    client: TestClient, cbe_bank: Any, db_session: Any
) -> None:
    """Fails closed. An unconfigured tenant must not be reachable, and the
    empty-key case is the one a `hmac.new(token, ...)` implementation gets
    wrong: HMAC with an empty key is perfectly valid, so anyone who signs with
    "" would be let in."""
    from bankassist.models import Bank

    bank = db_session.get(Bank, cbe_bank.id)
    bank.viber_auth_token = None
    db_session.commit()

    raw, headers = _signed({"event": "message"}, token="")
    resp = client.post("/webhooks/viber/cbe", content=raw, headers=headers)
    assert resp.status_code == 403


def test_valid_signature_helper_rejects_an_empty_token() -> None:
    body = b'{"event":"message"}'
    assert viber.valid_signature("", body, viber.signature("", body)) is False


def test_a_correctly_signed_message_is_answered(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """The honest case. Worth its own test: three refusal tests passing is
    also consistent with an endpoint that refuses everything."""
    resp = _say(client, "What are your savings rates?")
    assert resp.status_code == 200
    assert wired, "a signed message produced no reply at all"


# ------------------------------------------------------------------ events


def test_the_validation_ping_is_answered(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """Viber registers a webhook by POSTing `webhook` to it and refuses the
    registration unless that returns 200. Answering it is what makes connect
    possible at all — and it must not reach the agent, because there is no
    customer and no text."""
    raw, headers = _signed({"event": "webhook", "timestamp": 1})
    resp = client.post("/webhooks/viber/cbe", content=raw, headers=headers)
    assert resp.status_code == 200
    assert wired == []


@pytest.mark.parametrize("event", ["delivered", "seen", "failed", "unsubscribed"])
def test_receipts_are_not_conversations(
    client: TestClient, cbe_bank: Any, wired: list[Any], event: str
) -> None:
    """Delivery and read receipts arrive on the same endpoint. Treating one as
    a message would answer a customer who said nothing."""
    raw, headers = _signed({"event": event, "user_id": "u77"})
    resp = client.post("/webhooks/viber/cbe", content=raw, headers=headers)
    assert resp.status_code == 200
    assert wired == []


def test_a_sticker_gets_no_reply(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """Stickers, images and locations are `message` events with no text."""
    raw, headers = _signed(
        {"event": "message", "message": {"type": "sticker", "sticker_id": 1},
         "sender": {"id": "u77"}}
    )
    resp = client.post("/webhooks/viber/cbe", content=raw, headers=headers)
    assert resp.status_code == 200
    assert wired == []


def test_conversation_started_greets_without_answering(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """Viber's analogue of /start: the chat was opened, nothing was typed.
    Feeding it to the agent answers a question nobody asked."""
    raw, headers = _signed(
        {"event": "conversation_started", "user": {"id": "u77", "name": "A customer"}}
    )
    resp = client.post("/webhooks/viber/cbe", content=raw, headers=headers)
    assert resp.status_code == 200
    assert wired, "opening the chat said nothing at all"
    assert all("savings" not in text.lower() for _, _, text, _ in wired)


# -------------------------------------------------------------- disclaimer


def test_the_disclaimer_arrives_before_the_first_answer(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """Same rule as Telegram, and for the same reason: a bot is publicly
    reachable and has no pinned banner. Before, not after — a notice that
    follows the answer is not a notice."""
    _say(client, "What are your savings rates?")
    assert len(wired) >= 2, "expected a disclaimer and an answer"
    assert wired[0][2] == cbe_bank.disclaimer


def test_the_disclaimer_is_sent_once_not_on_every_message(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """Repeating it trains people to scroll past it."""
    _say(client, "What are your savings rates?")
    _say(client, "And current accounts?")
    assert [t for _, _, t, _ in wired].count(cbe_bank.disclaimer) == 1


def test_a_returning_customer_who_never_opened_a_new_chat_still_gets_it(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """`conversation_started` only fires on a fresh chat. Tying the disclaimer
    to that event would skip it for anyone messaging an existing thread, so it
    is tied to the conversation row being new instead."""
    _say(client, "Hello?", user="never-seen-before")
    assert wired[0][2] == cbe_bank.disclaimer


# ------------------------------------------------------------------ replies


def test_the_reply_is_addressed_to_the_sender(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """A crossed receiver id sends one customer's answer to another."""
    _say(client, "What are your savings rates?", user="u-alice")
    assert {receiver for _, receiver, _, _ in wired} == {"u-alice"}


def test_two_customers_do_not_share_a_conversation(
    client: TestClient, cbe_bank: Any, wired: list[Any], db_session: Any
) -> None:
    """Conversations are keyed by (bank, channel, external id). Without the
    external id in the lookup, two Viber customers would land in one thread
    and each would see the other's history."""
    from sqlalchemy import select

    from bankassist.models import Conversation

    _say(client, "Hello", user="u-alice")
    _say(client, "Hello", user="u-bob")

    rows = db_session.execute(
        select(Conversation).where(
            Conversation.bank_id == cbe_bank.id, Conversation.channel == "viber"
        )
    ).scalars().all()
    assert len({r.external_user_id for r in rows}) == 2


def test_viber_conversations_are_not_web_conversations(
    client: TestClient, cbe_bank: Any, wired: list[Any], db_session: Any
) -> None:
    """The channel column is what the analytics breakdown counts, and what a
    teller sees as the customer's origin."""
    from sqlalchemy import select

    from bankassist.models import Conversation

    _say(client, "Hello", user="u-alice")
    row = db_session.execute(
        select(Conversation).where(Conversation.external_user_id == "u-alice")
    ).scalar_one()
    assert row.channel == "viber"


# ------------------------------------------------------------------ adapter


def test_a_viber_error_inside_a_200_is_not_success() -> None:
    """Viber reports failures with HTTP 200 and a non-zero `status`. Trusting
    the status code alone means a rejected token reads as a delivered
    message, and nothing anywhere says the customer heard nothing."""
    import httpx

    resp = httpx.Response(
        200, json={"status": 3, "status_message": "invalid auth token"},
        request=httpx.Request("POST", "https://chatapi.viber.com/pa/send_message"),
    )
    assert viber._ok(resp) is False

    good = httpx.Response(
        200, json={"status": 0, "status_message": "ok"},
        request=httpx.Request("POST", "https://chatapi.viber.com/pa/send_message"),
    )
    assert viber._ok(good) is True


def test_a_long_answer_is_truncated_rather_than_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over 7,000 characters Viber rejects the message — as a 200, so it
    disappears silently. A visibly clipped answer beats no answer."""
    import httpx

    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured.update(kwargs["json"])
        return httpx.Response(
            200, json={"status": 0}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    assert viber.send_message(TOKEN, "u1", "x" * 9000, "CBE") is True
    assert len(captured["text"]) == viber.MAX_TEXT
