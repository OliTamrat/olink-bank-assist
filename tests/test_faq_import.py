"""Reading a bank's own published FAQ page in, instead of retyping it.

A bank's FAQ is the best content it owns and the only content that arrives in
exactly the shape the `faqs` table wants: somebody has already decided which
questions matter and written the approved answer to each. The reason a bank
with forty published answers ends up with four curated is that the only way in
was typing them back one at a time.

Two properties carry this feature, and neither is about parsing:

- **Imports land as drafts.** `approved_by` is the whole difference between a
  curated answer and a cache with extra steps, and an import has nobody's name
  on it.
- **Under-detection is the correct failure.** Curated answers are the one path
  with nothing downstream to catch a mistake — no retrieval gate, no
  INSUFFICIENT_CONTEXT, no sources for anyone to check. A missed question costs
  one manual entry; an invented one costs the bank's credibility.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import faq
from bankassist.models import Faq

PAGE = """Frequently Asked Questions

How do I open an account?
Visit any branch with a valid ID and one passport photograph.
Your account is usually active the same day.

What is the minimum balance on a savings account?
One hundred birr.

Q: Card activation
A: A branch officer activates the card, for security reasons.
"""


def _import(client: TestClient, bank: Any, **body: Any) -> Any:
    return client.post(
        "/admin/api/demo/faq/import",
        json={"text": PAGE, **body},
        headers={"X-Admin-Token": bank.admin_token},
    )


# ------------------------------------------------------------------ parsing


def test_a_question_mark_starts_a_pair_and_the_rest_is_the_answer() -> None:
    found = faq.pairs(PAGE)
    assert found[0].question == "How do I open an account?"
    assert "passport photograph" in found[0].answer
    assert "same day" in found[0].answer


def test_a_labelled_question_is_read_even_without_a_question_mark() -> None:
    """FAQ pages whose questions are statements are common, and would be
    invisible to a question-mark rule alone."""
    assert faq.pairs(PAGE)[2] == (
        "Card activation",
        "A branch officer activates the card, for security reasons.",
    )


def test_an_ethiopic_question_mark_counts() -> None:
    """Amharic must not have a worse import rate than English for punctuation
    reasons alone — the same doctrine as `normalise`."""
    found = faq.pairs("ሒሳብ እንዴት እከፍታለሁ፧\nማንኛውንም ቅርንጫፍ ይጎብኙ።")
    assert len(found) == 1
    assert found[0].answer == "ማንኛውንም ቅርንጫፍ ይጎብኙ።"


def test_prose_is_not_mistaken_for_questions() -> None:
    """The failure that matters. A looser rule turns headings and body text
    into answers served verbatim to customers."""
    assert faq.pairs(
        "Our Services\nWe offer savings, loans and foreign exchange.\n"
        "Visit us today\nBranches are open until five."
    ) == []


def test_a_question_with_no_answer_under_it_is_dropped() -> None:
    """A heading that happens to end in a question mark, with the answer
    behind a click that was never expanded."""
    assert faq.pairs("Need help?\n\nWhat is a PIN?\nA four digit code.") == [
        ("What is a PIN?", "A four digit code.")
    ]


def test_a_paragraph_ending_in_a_question_mark_is_not_a_question() -> None:
    """`Faq.question` is 400 characters. Anything longer is prose that happens
    to end in punctuation, and would create a key nobody will ever type."""
    assert faq.pairs("x " * 300 + "?\nAn answer.") == []


def test_the_same_question_twice_yields_one_pair() -> None:
    """Two rows under one key is a database error at write time and a race over
    which answer a customer sees."""
    found = faq.pairs(
        "What is Amole?\nA digital wallet.\nWhat is amole?\nSee above."
    )
    assert len(found) == 1
    assert found[0].answer == "A digital wallet."


# ------------------------------------------------------------------ the API


def test_preview_writes_nothing(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    before = len(db_session.execute(select(Faq)).scalars().all())
    resp = client.post(
        "/admin/api/demo/faq/import/preview",
        json={"text": PAGE},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    assert resp.status_code == 200
    assert len(resp.json()["pairs"]) == 3
    db_session.expire_all()
    assert len(db_session.execute(select(Faq)).scalars().all()) == before


def test_an_empty_preview_says_what_to_do_next(
    client: TestClient, demo_bank: Any
) -> None:
    body = client.post(
        "/admin/api/demo/faq/import/preview",
        json={"text": "Savings\nLoans\nForeign exchange"},
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    assert body["pairs"] == []
    assert body["note"] and "question mark" in body["note"]


def test_imported_answers_are_drafts_with_nobody_approving_them(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The property this whole feature rests on. Publishing on import would put
    the bank's name on wording nobody at the bank has read, at the one point
    where nothing downstream can catch it."""
    assert _import(client, demo_bank).status_code == 200
    db_session.expire_all()
    rows = db_session.execute(
        select(Faq).where(Faq.question == "How do I open an account?")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "draft"
    assert rows[0].approved_by is None
    assert rows[0].approved_at is None


def test_a_draft_import_is_not_served_to_customers(
    client: TestClient, demo_bank: Any
) -> None:
    """The end-to-end version of the same property: importing a page must not
    change one word of what a customer reads until somebody publishes it."""
    _import(client, demo_bank)
    reply = client.post(
        "/chat/demo",
        json={"message": "What is the minimum balance on a savings account?"},
    ).json()
    assert reply["reply"].strip() != "One hundred birr."


def test_only_the_ticked_questions_are_written(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    _import(client, demo_bank, questions=["What is the minimum balance on a savings account?"])
    db_session.expire_all()
    stored = {
        r.question for r in db_session.execute(select(Faq)).scalars().all()
    }
    assert "What is the minimum balance on a savings account?" in stored
    assert "How do I open an account?" not in stored


def test_an_existing_answer_is_never_overwritten(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A stale copy of a page must not undo a correction somebody made
    deliberately."""
    client.post(
        "/admin/api/demo/faq",
        json={
            "question": "How do I open an account?",
            "answer": "The corrected answer.",
            "status": "published",
        },
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    body = _import(client, demo_bank).json()
    assert body["skipped"] == 1
    db_session.expire_all()
    rows = db_session.execute(
        select(Faq).where(Faq.question == "How do I open an account?")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].answer == "The corrected answer."
    assert rows[0].status == "published"


def test_the_preview_says_which_ones_are_already_answered(
    client: TestClient, demo_bank: Any
) -> None:
    """"Three new, one you already publish" is a different decision from
    "four new"."""
    client.post(
        "/admin/api/demo/faq",
        json={
            "question": "How do I open an account?",
            "answer": "Ours.",
            "status": "published",
        },
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    pairs = client.post(
        "/admin/api/demo/faq/import/preview",
        json={"text": PAGE},
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()["pairs"]
    held = {p["question"]: p["existing"] for p in pairs}
    assert held["How do I open an account?"] == "published"
    assert held["What is the minimum balance on a savings account?"] is None


def test_import_needs_documents_write(client: TestClient, demo_bank: Any) -> None:
    """Same bar as editing the knowledge base, because it is the same act."""
    assert client.post(
        "/admin/api/demo/faq/import", json={"text": PAGE}
    ).status_code in (401, 403)


def test_another_banks_page_cannot_be_imported_into_this_one(
    client: TestClient, demo_bank: Any, second_bank: Any
) -> None:
    _import(client, demo_bank)
    rows = client.get(
        "/admin/api/other/faq", headers={"X-Admin-Token": second_bank.admin_token}
    ).json()
    assert rows == []
