"""What a customer is offered after a miss should be a question, not a label.

The founder's screenshots of CBE's own "Selam" bot are the argument: it offers
follow-ups phrased the way a person speaks — "SWIFT code for Commercial Bank of
Ethiopia (CBE)" — where this product offered filing labels, "ATM and Debit
Cards". A question is a thing a customer taps. A topic is a thing they have to
translate back into a question first, on the one screen where they have already
failed once.

The material was already there: `Faq` holds real customer-phrased questions, per
language, published, and served verbatim with no model in the path. So the chip
now carries one of those when the bank has a relevant one, and tapping it lands
straight on the bank's own approved answer.

What must not move, and is what most of this file tests:

* a suggestion is still text the BANK wrote, offered verbatim — never composed;
* a draft is never advertised, any more than it is served;
* a question is never offered across a tenant or across a language, because a
  chip is tapped and whatever it says is asked as the next message;
* a bank that has curated nothing still gets document titles, exactly as before;
* and tapping a chip goes through the whole pipeline again, so no guardrail is
  anywhere near this path.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bankassist import faq
from bankassist.i18n import t
from bankassist.models import Faq
from bankassist.retrieval import suggest

# A topic no seeded corpus covers, so a question about it is always a miss and
# the only thing that can answer it is a curated entry.
OSTRICH_Q = "Do you finance ostrich farms?"
OSTRICH_A = "Yes — ostrich farming is eligible under our agri-business loan."


def _publish(
    client: TestClient, bank: Any, question: str, answer: str = OSTRICH_A,
    language: str = "en", status: str = "published",
) -> str:
    resp = client.post(
        f"/admin/api/{bank.slug}/faq",
        json={"question": question, "answer": answer,
              "language": language, "status": status},
        headers={"X-Admin-Token": bank.admin_token},
    )
    assert resp.status_code == 201, resp.text
    fid: str = resp.json()["id"]
    return fid


def _ask(client: TestClient, slug: str, message: str, language: str = "en") -> Any:
    resp = client.post(
        f"/chat/{slug}", json={"message": message, "language": language}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ------------------------------------------------------------ what is offered


def test_a_miss_offers_the_banks_own_published_questions(
    client: TestClient, demo_bank: Any
) -> None:
    _publish(client, demo_bank, OSTRICH_Q)
    data = _ask(client, "demo", "anything for someone starting an ostrich farm?")

    assert data["handoff_created"] is True, "setup: this has to be a miss"
    assert data["suggestions"], "a miss must offer somewhere to go"
    assert [s["title"] for s in data["suggestions"]] == [OSTRICH_Q]
    assert data["suggestions"][0]["faq_id"], "offered as a question, not a topic"
    assert data["suggestions"][0]["document_id"] is None


def test_the_offered_question_is_the_stored_one_word_for_word(
    client: TestClient, db_session: Session, demo_bank: Any
) -> None:
    """The safety property the whole feature rests on. A generated question
    would be the assistant putting words in the bank's mouth on the one path
    that ends in an answer served with no model and no gate after it."""
    fid = _publish(client, demo_bank, OSTRICH_Q)
    data = _ask(client, "demo", "ostrich farm")

    offered = data["suggestions"][0]
    assert offered["faq_id"] == fid
    assert offered["title"] == db_session.get(Faq, fid).question


def test_tapping_the_offered_question_returns_the_curated_answer(
    client: TestClient, demo_bank: Any
) -> None:
    """The point of offering a question rather than a label: the chip sends
    its own text as the next message, and that text is the exact key the
    curated lookup wants. A customer who could not phrase it gets the bank's
    approved wording in one tap."""
    _publish(client, demo_bank, OSTRICH_Q)
    first = _ask(client, "demo", "ostrich farm finance")
    tapped = first["suggestions"][0]["title"]

    second = client.post(
        "/chat/demo",
        json={"message": tapped, "language": "en",
              "conversation_id": first["conversation_id"]},
    ).json()

    assert second["reply"] == OSTRICH_A
    assert second["handoff_created"] is False, "the chip closed the loop"


def test_a_draft_is_never_offered(client: TestClient, demo_bank: Any) -> None:
    """A draft is not served, so advertising one would be a chip that leads
    somewhere worse than where the customer already is."""
    _publish(client, demo_bank, OSTRICH_Q, status="draft")
    data = _ask(client, "demo", "ostrich farm finance")

    assert OSTRICH_Q not in [s["title"] for s in data["suggestions"]]
    assert all(s["faq_id"] is None for s in data["suggestions"])


def test_a_question_is_never_offered_across_tenants(
    client: TestClient, demo_bank: Any, cbe_bank: Any
) -> None:
    """The same leak the document rule has always been held to: a suggestion
    must never reveal that another bank has content on something."""
    _publish(client, demo_bank, OSTRICH_Q)
    data = _ask(client, "cbe", "anything for an ostrich farm?")

    assert OSTRICH_Q not in [s["title"] for s in data["suggestions"]]


def test_a_question_is_never_offered_across_languages(
    client: TestClient, demo_bank: Any
) -> None:
    """A chip is tapped, and whatever it says is asked as the next message —
    so offering an English question to somebody writing Amharic answers them
    in English through the one path with no gate after it.

    The two rows carry the SAME text on purpose. Any difference in wording
    would let token overlap explain the result; identical text leaves the
    language filter as the only thing that can be doing the work.
    """
    english = _publish(client, demo_bank, OSTRICH_Q, language="en")
    amharic = _publish(client, demo_bank, OSTRICH_Q, language="am")

    data = _ask(client, "demo", "ostrich farm finance", language="en")
    offered = {s["faq_id"] for s in data["suggestions"]}
    assert english in offered
    assert amharic not in offered


# ------------------------------------------------------- and in what order


def test_a_relevant_title_beats_an_irrelevant_question(
    client: TestClient, db_session: Session, demo_bank: Any
) -> None:
    """Shape is worth less than relevance. A published question is the better
    chip only while it is about what was asked; otherwise the near-miss
    document is still the most useful thing this bank has."""
    _publish(client, demo_bank, OSTRICH_Q)

    hits = suggest(db_session, demo_bank.id, "savings account interest", "en")
    assert hits
    assert all(s.faq_id is None for s in hits), (
        "an ostrich question was offered to somebody asking about savings"
    )
    assert all(s.document_id for s in hits)


def test_when_nothing_matches_the_most_asked_questions_are_the_cold_start(
    client: TestClient, db_session: Session, demo_bank: Any
) -> None:
    """Gibberish, or a topic genuinely absent. A menu of what people actually
    ask is a better opening than a list of the bank's longest documents."""
    quiet = _publish(client, demo_bank, OSTRICH_Q)
    busy = _publish(client, demo_bank, "Where is my nearest branch?", "Use the app.")
    for _ in range(3):
        client.post("/chat/demo", json={"message": "Where is my nearest branch?",
                                        "language": "en"})

    hits = suggest(db_session, demo_bank.id, "zzzz qqqq vvvv", "en")
    assert [s.faq_id for s in hits][:2] == [busy, quiet], (
        "the cold-start menu is ordered by what customers actually ask"
    )


def test_a_bank_that_has_curated_nothing_still_gets_document_titles(
    client: TestClient, cbe_bank: Any
) -> None:
    """The fallback is the whole of the previous behaviour, and most tenants
    are still on it — no bank should get a worse miss for not having curated
    anything yet."""
    data = _ask(client, "cbe", "zzzz qqqq unrelated nonsense phrase")

    assert data["suggestions"]
    assert all(s["document_id"] for s in data["suggestions"])
    assert all(s["faq_id"] is None for s in data["suggestions"])


# --------------------------------------------------------- and how it reads


def test_the_questions_are_in_the_reply_text_under_their_own_intro(
    client: TestClient, demo_bank: Any
) -> None:
    """Telegram sends `result.reply` and renders no chips, so a suggestion
    living only in the JSON field is invisible there.

    And the sentence above the list has to match what is under it: "these
    related topics may help" over a list of whole questions describes
    something the customer is not looking at.
    """
    _publish(client, demo_bank, OSTRICH_Q)
    data = _ask(client, "demo", "our ostrich business needs support")

    assert OSTRICH_Q in data["reply"]
    assert t("en", "related_questions") in data["reply"]
    assert t("en", "related_topics") not in data["reply"]


def test_a_confident_answer_still_carries_no_suggestions(
    client: TestClient, demo_bank: Any
) -> None:
    """Curated questions are a miss affordance too. Attaching them to a good
    answer would imply the assistant is unsure when it isn't."""
    _publish(client, demo_bank, OSTRICH_Q)
    data = _ask(client, "demo", "How do I open a savings account?")

    assert data["sources"], "expected a real retrieval hit for this phrasing"
    assert data["suggestions"] == []


def test_a_curated_question_cannot_carry_anything_past_a_guardrail(
    client: TestClient, demo_bank: Any
) -> None:
    """A chip is navigation: tapping it asks an ordinary message, which runs
    the whole pipeline again. So even a question a bank should never have
    published gets the account refusal rather than its own answer — the
    curated lookup sits after every guardrail and being suggested changes
    nothing about that."""
    _publish(client, demo_bank, "What is my account balance?", "It is 5,000 birr.")
    data = _ask(client, "demo", "What is my account balance?")

    assert data["reply"] != "It is 5,000 birr."
    assert data["reply"] == t("en", "account_help")


def test_the_offered_question_is_not_counted_as_served(
    client: TestClient, db_session: Session, demo_bank: Any
) -> None:
    """`served` is what tells a bank whether curating more of these is worth
    an afternoon. Counting an offer as a serving would inflate it with
    answers nobody read."""
    fid = _publish(client, demo_bank, OSTRICH_Q)
    _ask(client, "demo", "ostrich farm")

    db_session.expire_all()
    assert db_session.get(Faq, fid).served == 0


def test_the_lookup_key_of_an_offered_question_is_the_question_itself(
    client: TestClient, db_session: Session, demo_bank: Any
) -> None:
    """Belt and braces on the closed loop, at the level where it could break
    silently: whatever normalisation `faq.key` grows, the text on the chip
    has to keep resolving to the row it came from."""
    fid = _publish(client, demo_bank, OSTRICH_Q)
    offered = suggest(db_session, demo_bank.id, "ostrich", "en")[0]

    assert faq.key(offered.title, "en") == db_session.get(Faq, fid).lookup
