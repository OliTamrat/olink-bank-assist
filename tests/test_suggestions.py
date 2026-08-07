"""Retrieval is lexical, so a customer whose phrasing doesn't match the
knowledge base gets nothing — and almost nobody rephrases to match a corpus
they can't see. These lock in that a miss offers real topics to pick from
instead of dead-ending, without weakening the informativeness gate that
stops confidently-wrong answers.

The safety property under test: a suggestion is always an existing document
title belonging to *this* bank. Offering one is navigation, not guessing, so
it can never fabricate a product, rate or requirement.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bankassist.models import Document
from bankassist.retrieval import suggest_topics


def _ask(client: TestClient, slug: str, message: str) -> dict[str, Any]:
    resp = client.post(f"/chat/{slug}", json={"message": message})
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def test_padded_phrasing_that_misses_still_offers_topics(
    client: TestClient, cbe_bank: Any
) -> None:
    # The documented failure mode: a query padded with a bank/account suffix
    # fails the length-gated informativeness ratio even though the topic is
    # covered. It must not dead-end.
    data = _ask(client, "cbe", "How can I protect myself from fraud on my CBE account?")
    if data["handoff_created"]:
        assert data["suggestions"], "a miss must offer somewhere to go"
        assert all(s["title"] for s in data["suggestions"])


def test_gibberish_still_offers_topics_rather_than_a_closed_door(
    client: TestClient, cbe_bank: Any
) -> None:
    data = _ask(client, "cbe", "asdkfjhaslkdjf 12345 ???")
    assert data["handoff_created"] is True
    assert data["sources"] == [], "must not claim a source it didn't use"
    assert data["suggestions"], "even a total miss should offer a way forward"


def test_suggestions_are_real_documents_of_this_bank_only(
    client: TestClient, db_session: Session, cbe_bank: Any, dashen_bank: Any
) -> None:
    # Tenancy: a suggestion must never surface another bank's document, which
    # would leak the existence of a competitor's content.
    data = _ask(client, "cbe", "zzzz qqqq unrelated nonsense phrase")
    assert data["suggestions"]
    ids = [s["document_id"] for s in data["suggestions"]]
    owners = {
        doc.bank_id
        for doc in db_session.query(Document).filter(Document.id.in_(ids)).all()
    }
    assert owners == {cbe_bank.id}


def test_a_confident_answer_does_not_carry_suggestions(
    client: TestClient, cbe_bank: Any
) -> None:
    # Suggestions are a miss affordance. Attaching them to a good answer
    # would imply the assistant is unsure when it isn't.
    data = _ask(client, "cbe", "How do I open a diaspora account?")
    assert data["sources"], "expected a real retrieval hit for this phrasing"
    assert data["suggestions"] == []


def test_handoff_is_still_created_when_suggestions_are_offered(
    client: TestClient, cbe_bank: Any
) -> None:
    # Suggestions must not paper over a genuine knowledge gap — the bank
    # still needs every gap visible as content work.
    data = _ask(client, "cbe", "qqqq zzzz vvvv unrelated")
    assert data["handoff_created"] is True
    assert data["suggestions"]


def test_suggest_topics_prefers_near_misses_over_generic_breadth(
    db_session: Session, cbe_bank: Any
) -> None:
    # A query that scores against a real topic should surface that topic,
    # not the widest-document fallback.
    hits = suggest_topics(db_session, cbe_bank.id, "diaspora")
    assert hits, "a scoring query should produce near-miss suggestions"
    assert any("diaspora" in s.title.lower() for s in hits)


def test_suggest_topics_is_bounded_and_deduplicated(
    db_session: Session, cbe_bank: Any
) -> None:
    hits = suggest_topics(db_session, cbe_bank.id, "account", limit=3)
    assert len(hits) <= 3
    assert len({s.document_id for s in hits}) == len(hits), "one doc must not fill slots"


def test_empty_corpus_offers_nothing_rather_than_erroring(
    db_session: Session, cbe_bank: Any
) -> None:
    assert suggest_topics(db_session, "no-such-bank-id", "anything") == []
