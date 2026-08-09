"""The prospect-demo disclaimer has to survive the jump to Telegram.

In the widget the disclaimer is a banner pinned above every message, and the
widget only ever reaches someone already on a page the bank controls. A bot is
the opposite on both counts: it is publicly discoverable by username, anyone
can open a chat with it, and there is no persistent surface to hold a notice.

So for a tenant like CBE — a bot wearing a bank's name that the bank has not
endorsed — an unlabelled first reply is the most consequential thing this
product could get wrong. It is also the kind of thing that breaks silently:
the assistant still answers perfectly, and nothing anywhere reports that the
notice was skipped. Hence a test rather than a comment.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

HEADER = {"X-Telegram-Bot-Api-Secret-Token": "s3cret"}


@pytest.fixture()
def wired(
    client: TestClient, cbe_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, int | str, str]]:
    """A CBE tenant with a bot connected, and every outbound message captured."""
    from bankassist import api as api_module
    from bankassist.models import Bank

    bank = db_session.get(Bank, cbe_bank.id)
    bank.telegram_webhook_secret = "s3cret"
    bank.telegram_bot_token = "123:abc"
    db_session.commit()

    sent: list[tuple[str, int | str, str]] = []
    monkeypatch.setattr(
        api_module.telegram,
        "send_message",
        lambda token, chat_id, text: sent.append((token, chat_id, text)) or True,
    )
    return sent


def _say(client: TestClient, text: str, chat_id: int = 77) -> None:
    resp = client.post(
        "/webhooks/telegram/cbe",
        json={"message": {"text": text, "chat": {"id": chat_id}}},
        headers=HEADER,
    )
    assert resp.status_code == 200, resp.text


def test_the_disclaimer_arrives_before_the_first_answer(
    client: TestClient, cbe_bank: Any, wired: list[tuple[str, int | str, str]]
) -> None:
    """Before, not after. A notice that follows the answer is not a notice."""
    _say(client, "What are your savings rates?")
    assert len(wired) == 2, "expected the disclaimer and then the reply"
    assert "Unofficial prototype" in wired[0][2]
    assert "not affiliated" in wired[0][2].lower()
    assert wired[0][2] != wired[1][2]


def test_it_is_sent_once_and_not_on_every_message(
    client: TestClient, cbe_bank: Any, wired: list[tuple[str, int | str, str]]
) -> None:
    """Repeating it every turn is how people learn to scroll past it."""
    _say(client, "What are your savings rates?")
    _say(client, "And the fixed deposit rates?")
    _say(client, "Thanks")
    disclaimers = [m for m in wired if "Unofficial prototype" in m[2]]
    assert len(disclaimers) == 1


def test_a_different_chat_gets_its_own_disclaimer(
    client: TestClient, cbe_bank: Any, wired: list[tuple[str, int | str, str]]
) -> None:
    """Once per conversation, not once per bank — a second customer is a
    second person who has never seen it."""
    _say(client, "Hello", chat_id=77)
    _say(client, "Hello", chat_id=88)
    assert len([m for m in wired if "Unofficial prototype" in m[2]]) == 2


def test_start_gets_the_greeting_rather_than_an_answer(
    client: TestClient, cbe_bank: Any, wired: list[tuple[str, int | str, str]]
) -> None:
    """`/start` is Telegram opening the bot, not a customer's question.

    Handing it to the agent produces a confident answer to something nobody
    asked — the worst possible first impression for a banking assistant.
    """
    _say(client, "/start")
    assert len(wired) == 2
    assert "Unofficial prototype" in wired[0][2]
    assert "virtual assistant" in wired[1][2].lower()


def test_start_with_a_deep_link_payload_is_still_start(
    client: TestClient, cbe_bank: Any, wired: list[tuple[str, int | str, str]]
) -> None:
    """Telegram appends a referral payload: `/start ref123`. A bare equality
    check on the text treats that as a question and answers it."""
    _say(client, "/start campaign_2026")
    assert "virtual assistant" in wired[-1][2].lower()


def test_a_tenant_with_no_disclaimer_sends_nothing_extra(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The demo bank is our own and carries no disclaimer. It must not gain a
    blank leading message — an empty first bubble looks like a broken bot."""
    from bankassist import api as api_module
    from bankassist.models import Bank

    bank = db_session.get(Bank, demo_bank.id)
    bank.telegram_webhook_secret = "s3cret"
    bank.telegram_bot_token = "123:abc"
    db_session.commit()

    sent: list[tuple[str, int | str, str]] = []
    monkeypatch.setattr(
        api_module.telegram,
        "send_message",
        lambda token, chat_id, text: sent.append((token, chat_id, text)) or True,
    )
    resp = client.post(
        "/webhooks/telegram/demo",
        json={"message": {"text": "What are the fixed deposit rates?", "chat": {"id": 9}}},
        headers=HEADER,
    )
    assert resp.status_code == 200
    assert len(sent) == 1
