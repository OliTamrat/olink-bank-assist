"""An email address is not an answer to "my app has stopped working".

Reported from the live CBE demo, minutes after the SERVICE_ISSUE change
(ADR-0023) started routing broken-thing questions to the knowledge base
instead of straight to a teller. The routing worked. The answer was:

    > For help with your mobile banking app, you can reach CBE's e-payments
    > support at epaymentsupport@cbe.com.et.

The founder's verdict was correct: that is not help. And it is worse than a
thin corpus, because the retrieved context *did* contain a usable answer —
"If you cannot use the app, standard mobile banking services are also
available by dialing *889# from your registered phone number" — sitting in
the same document, in the same chunk, as the email the model chose instead.

So two rules the generation prompt did not previously state:

1. **Steps beat referrals.** If the context holds a workaround, an
   alternative channel or a self-service option, that is the answer. A
   contact detail is a last resort offered *after* the steps.
2. **A referral alone is a decline.** If the only relevant thing the context
   offers is "contact us", the question has not been answered — return
   INSUFFICIENT_CONTEXT so the turn takes the miss path, where general
   knowledge can offer the universal troubleshooting steps and the bank gets
   a content gap telling it to publish its own.

**These are prompt changes, and a prompt cannot be unit-tested from a
sandbox with no model.** What IS tested here is everything downstream of the
decline — that the miss path does something better than the referral did.
The prompt's own behaviour needs a live check against the deployed widget;
see the ADR.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bankassist import agent, llm
from bankassist.models import Handoff

BROKEN_APP = "my mobile banking app is not working, what should I do?"


@pytest.fixture
def _declines(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model behaving the way the new rule 2 tells it to.

    Before this change it returned the support email here; the point of the
    prompt edit is that this case becomes a decline.
    """

    def declined(*args: Any, **kwargs: Any) -> str:
        raise llm.LLMDeclined(llm.INSUFFICIENT_CONTEXT)

    monkeypatch.setattr(agent, "generate_answer", declined)


def test_a_declined_service_issue_reaches_general_knowledge(
    client: TestClient, cbe_bank: Any, _declines: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of declining rather than shipping the referral.

    Universal first-line troubleshooting is exactly what the
    general-knowledge path exists for — identical on every banking app ever
    written — and it is worth more to a locked-out customer than an inbox.
    """
    monkeypatch.setattr(
        agent,
        "answer_from_general_knowledge",
        lambda *a, **k: "Check your connection, close and reopen the app, "
        "then install any pending update.",
    )
    data = client.post("/chat/cbe", json={"message": BROKEN_APP}).json()
    assert "close and reopen" in data["reply"]
    # Labelled, and carrying no sources, so it can never read as the bank
    # speaking — the boundary that makes this path safe at all.
    assert data["general_knowledge"] is True
    assert data["sources"] == []


def test_a_declined_service_issue_still_becomes_a_content_gap(
    client: TestClient,
    db_session: Session,
    cbe_bank: Any,
    _declines: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bank must learn it has no troubleshooting content of its own.

    Universal steps are a floor, not the fix. The durable answer is CBE
    publishing "what to do when the app will not open", and the only thing
    that ever prompts that is the gap showing up in their own report.
    """
    monkeypatch.setattr(
        agent, "answer_from_general_knowledge", lambda *a, **k: "Try reopening the app."
    )
    client.post("/chat/cbe", json={"message": BROKEN_APP})
    reasons = [
        h.reason
        for h in db_session.query(Handoff).filter_by(bank_id=cbe_bank.id).all()
    ]
    assert agent.REASON_GENERAL_KNOWLEDGE in reasons


def test_nobody_is_left_with_nothing_when_general_knowledge_also_declines(
    client: TestClient, cbe_bank: Any, _declines: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The floor under the floor.

    If neither the documents nor universal guidance can help, a person can —
    and that is still a better outcome than an email address, because the
    handoff is a promise somebody is on the hook for.
    """

    def also_declines(*args: Any, **kwargs: Any) -> str:
        raise llm.LLMDeclined(llm.INSUFFICIENT_CONTEXT)

    monkeypatch.setattr(agent, "answer_from_general_knowledge", also_declines)
    data = client.post("/chat/cbe", json={"message": BROKEN_APP}).json()
    assert data["handoff_created"] is True


# --------------------------------------------------------------- the prompt

# These read the prompt text itself. That is weaker than exercising it — it
# proves the instruction is present, not that the model obeys it — but a
# silent deletion of a rule written in response to a live defect is worth
# catching, and this is the only part of a prompt a sandbox can check.


def test_the_prompt_tells_the_model_that_steps_beat_referrals() -> None:
    prompt = llm._SYSTEM_PROMPT.lower()
    assert "last resort" in prompt
    assert "workaround" in prompt


def test_the_prompt_tells_the_model_a_referral_alone_is_a_decline() -> None:
    assert "INSUFFICIENT_CONTEXT" in llm._SYSTEM_PROMPT
    lowered = llm._SYSTEM_PROMPT.lower()
    assert "contact detail" in lowered or "referral" in lowered


def test_general_knowledge_is_allowed_to_troubleshoot_an_app() -> None:
    """Declining is only an improvement if something useful catches it.

    Without this clause the decline would fall straight through to the miss
    path and the customer would be worse off than with the email.
    """
    assert "troubleshooting" in llm._GENERAL_PROMPT.lower()


def test_the_general_knowledge_boundary_is_not_widened_by_that_clause() -> None:
    """The clause must not become a hole in the figure-free rule.

    Everything that made general knowledge safe stays named in the prompt:
    no rates, no limits, nothing specific to this bank.
    """
    lowered = llm._GENERAL_PROMPT.lower()
    for forbidden in ("interest rate", "limit", "branch locations", "specific to"):
        assert forbidden in lowered
