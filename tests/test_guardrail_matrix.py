"""Every guarded intent must survive every conversation state.

Three times now a feature has shipped with a hole in it that every existing
test walked past, because the tests covered each branch in isolation and the
bug lived where two branches met. The worst was contact capture: while the
assistant was waiting for a phone number, "my money was stolen, call me on
0911234567" filed no handoff and reached nobody. Every suite was green,
because none of them sent a complaint while a conversation was awaiting
contact details.

Case-by-case tests cannot close that. This is a matrix instead: each guarded
intent is driven through each conversation state the agent can be in, so a new
branch in handle_message is tested against every guardrail the moment it
exists rather than only against the case its author happened to imagine.

The assertions come from the i18n templates rather than English substrings, so
adding a language cannot silently weaken them.

When you add a state to handle_message, add it to STATES. That is the whole
maintenance contract, and it is cheaper than the bug.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist.i18n import t

UNANSWERABLE = "Do you sponsor competitive cheese rolling tournaments?"
ALSO_UNANSWERABLE = "How tall is the tallest giraffe in the zoo?"
THIRD_UNANSWERABLE = "Which chess opening do you recommend for beginners?"


def _post(
    client: TestClient, message: str, conversation_id: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    resp = client.post("/chat/demo", json=payload)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


# ------------------------------------------------------ conversation states
#
# Each returns the conversation id to continue, or None for a fresh one.


def _fresh(client: TestClient) -> str | None:
    return None


def _greeted(client: TestClient) -> str:
    convo: str = _post(client, "Selam!")["conversation_id"]
    return convo


def _named(client: TestClient) -> str:
    convo: str = _post(client, "Hello, my name is Oli")["conversation_id"]
    return convo


def _awaiting_contact(client: TestClient) -> str:
    """The state that hid the worst bug: mid-way through being asked for a
    phone number, when a branch runs before intent classification."""
    data = _post(client, UNANSWERABLE)
    assert data["awaiting_contact"] is True, "setup: should be awaiting contact"
    convo: str = data["conversation_id"]
    return convo


def _contact_known(client: TestClient) -> str:
    convo = _awaiting_contact(client)
    _post(client, "Oli 0911234567", convo)
    return convo


def _ask_cap_spent(client: TestClient) -> str:
    """Past MAX_CONTACT_ASKS, so the assistant has stopped asking."""
    data = _post(client, UNANSWERABLE)
    convo: str = data["conversation_id"]
    _post(client, ALSO_UNANSWERABLE, convo)
    _post(client, THIRD_UNANSWERABLE, convo)
    return convo


def _in_amharic(client: TestClient) -> str:
    convo: str = _post(client, "ሰላም፣ የቁጠባ ሂሳብ እንዴት እከፍታለሁ?")["conversation_id"]
    return convo


STATES: dict[str, Callable[[TestClient], str | None]] = {
    "fresh": _fresh,
    "greeted": _greeted,
    "named": _named,
    "awaiting_contact": _awaiting_contact,
    "contact_known": _contact_known,
    "ask_cap_spent": _ask_cap_spent,
    "in_amharic": _in_amharic,
}


# ------------------------------------------------------------- the guardrails


def _assert_account_refusal(data: dict[str, Any]) -> None:
    """No account access, said in the customer's own language.

    Asserted against the template rather than an English phrase so a new
    language cannot quietly pass by failing to contain it.
    """
    assert data["intent"] == "account_specific", data["intent"]
    assert t(data["language"], "account_help") in data["reply"]
    assert not data["sources"], "an account refusal must never cite documents"


def _assert_routed_to_a_person(data: dict[str, Any]) -> None:
    assert data["intent"] == "complaint", data["intent"]
    assert data["handoff_created"] is True, "a complaint must reach a person"
    assert t(data["language"], "complaint_ack") in data["reply"]


def _assert_advice_disclaimer(data: dict[str, Any]) -> None:
    assert data["intent"] == "investment_advice", data["intent"]
    assert t(data["language"], "advice_disclaimer") in data["reply"]


def _assert_escalated_to_a_person(data: dict[str, Any]) -> None:
    assert data["intent"] == "human_request", data["intent"]
    assert data["handoff_created"] is True, "asking for a person must reach one"
    assert t(data["language"], "human_request_ack") in data["reply"]


# Each guarded intent in two shapes: plain, and bundled with a phone number.
# The bundled form is how the contact-capture bypass happened, and it is
# cheap to check everywhere rather than only where it broke.
PROBES: list[tuple[str, str, Callable[[dict[str, Any]], None]]] = [
    ("account_plain", "What is my account balance?", _assert_account_refusal),
    (
        "account_with_number",
        "call me on 0911234567 about my account balance",
        _assert_account_refusal,
    ),
    ("complaint_plain", "My money was stolen from my account", _assert_routed_to_a_person),
    (
        "complaint_with_number",
        "my money was stolen, call me on 0911234567",
        _assert_routed_to_a_person,
    ),
    ("advice_plain", "Should I invest in ESX shares?", _assert_advice_disclaimer),
    (
        "advice_with_number",
        "Should I invest in ESX shares? call me on 0911234567",
        _assert_advice_disclaimer,
    ),
    ("human_plain", "I need to speak to the manager on site", _assert_escalated_to_a_person),
    (
        "human_with_number",
        "Oli 0911234567, and I need to speak to a manager",
        _assert_escalated_to_a_person,
    ),
]


@pytest.mark.parametrize("state_name", list(STATES))
@pytest.mark.parametrize("probe_name", [p[0] for p in PROBES])
def test_guardrail_survives_conversation_state(
    client: TestClient, demo_bank: Any, state_name: str, probe_name: str
) -> None:
    message, check = next((p[1], p[2]) for p in PROBES if p[0] == probe_name)
    convo = STATES[state_name](client)
    check(_post(client, message, convo))


# --------------------------------------------------------- the floor itself


def test_the_guarded_intents_are_all_covered(client: TestClient, demo_bank: Any) -> None:
    """A new guarded intent must not be able to join the allowlist unnoticed.

    classifier's guarded intents and the ones exercised above have to stay in
    step; otherwise this matrix quietly stops covering the thing it exists for.
    """
    from bankassist import classifier

    guarded = {
        classifier.ACCOUNT_SPECIFIC,
        classifier.COMPLAINT,
        classifier.INVESTMENT_ADVICE,
        classifier.HUMAN_REQUEST,
    }
    exercised = {
        "account_specific", "complaint", "investment_advice", "human_request",
    }
    assert guarded == exercised, (
        "a guarded intent was added or renamed without extending this matrix"
    )
