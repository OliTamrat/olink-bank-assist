"""When the customer cannot write the question well.

Ethiopia is onboarding tens of millions of first-time digital banking users.
Many will not type a well-formed sentence: misspellings, two-word fragments,
words in the wrong order, no punctuation, often in a second language. Lexical
retrieval is unforgiving of all four.

**The failure that causes is not the one you would expect, and that is the
whole reason this exists.** Measured against the seeded CBE corpus:

    'how open acount'  ->  Transfers to Telebirr and Other Wallets
    (well-formed)      ->  Ordinary Savings Account

The typo kills `acount`; `open` matches "open" in an unrelated document.
Retrieval **succeeds, confidently, on the wrong thing**. The model then reads
it, correctly declines, and the customer is escalated to a teller — by a
mechanism that looks from the inside like the system working properly. It
would never show up as a bug.

Two layers answer it, and the order matters:

1. **Refine, silently.** On failure only — nothing retrieved, or the model
   declined — rewrite the message as a clear query in the customer's own
   language and search again. Only the SEARCH TEXT is rewritten, so a bad
   rewrite costs a miss and never a wrong answer.
2. **Ask, if still unsure.** Rather than fetching a person, offer the near-miss
   document titles as chips the customer can TAP. The people this exists for
   are exactly the people who cannot easily rephrase.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from bankassist import agent, llm
from bankassist.models import Bank, Conversation, Handoff, Message


def _turn(db: Session, bank: Bank, conv: Conversation, text: str) -> agent.ChatResult:
    """One exchange, persisted the way `api.py` persists it.

    The messages have to be written for real: `_may_clarify` counts them, so
    a test that skips the write would never see the budget run out.
    """
    result = agent.handle_message(db, bank, conv, text)
    db.add(Message(bank_id=bank.id, conversation_id=conv.id, role="user", text=text))
    db.add(
        Message(
            bank_id=bank.id,
            conversation_id=conv.id,
            role="assistant",
            text=result.reply,
            outcome=result.outcome,
        )
    )
    db.commit()
    return result


@pytest.fixture()
def conv(db_session: Session, cbe_bank: Bank) -> Conversation:
    conversation = Conversation(bank_id=cbe_bank.id, channel="web")
    db_session.add(conversation)
    db_session.flush()
    return conversation


# Nothing in any seeded corpus answers these, and they carry enough ordinary
# words for suggest_topics to find near misses.
UNCLEAR = "kebele id papers wereda thing"

# A rewrite that is DIFFERENT from the message and still finds nothing. That
# difference is the gate on the whole clarifying branch — see the comment in
# `agent.py`: it is the model's own judgement that the message was not clear,
# which is what separates "we misunderstood you" from "we have no content".
REWROTE = "what wereda kebele paperwork is needed"


@pytest.fixture()
def rewrites(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "refine_for_search", lambda _text: REWROTE)


# ------------------------------------------------------- asking back


def test_an_unclear_question_is_asked_about_not_escalated(
    db_session: Session, cbe_bank: Bank, conv: Conversation, rewrites: None
) -> None:
    result = _turn(db_session, cbe_bank, conv, UNCLEAR)
    assert result.outcome == agent.CLARIFYING
    # The turn must NOT claim somebody will follow up. It promises the
    # opposite: that we are still trying to answer it ourselves.
    assert result.handoff_created is False
    assert result.suggestions, "a clarifying question with nothing to offer is a dead end"


def test_the_chips_are_real_documents_of_this_bank(
    db_session: Session, cbe_bank: Bank, conv: Conversation, rewrites: None
) -> None:
    """suggest_topics invents nothing — pinned here because the clarify turn
    is a new caller of it, and an invented product name offered as a chip
    would be a hallucination with a tap target on it."""
    result = _turn(db_session, cbe_bank, conv, UNCLEAR)
    titles = {
        title for (title,) in db_session.query(agent.Document.title).filter_by(bank_id=cbe_bank.id)
    }
    for suggestion in result.suggestions:
        assert suggestion["title"] in titles


def test_the_clarify_turn_files_a_row_but_puts_nobody_in_a_queue(
    db_session: Session, cbe_bank: Bank, conv: Conversation, rewrites: None
) -> None:
    """Both halves matter and they pull in opposite directions.

    Filed, because "our content did not match how this customer writes" is
    real content-gap information and is invisible anywhere else. Not
    `needs_person`, because nobody is waiting for a callback — and a queue
    that fills with questions nobody has understood yet is a queue an
    operator cannot work. A bank opening one such queue found nine rows with
    no contact details and no way to tell which were real.
    """
    _turn(db_session, cbe_bank, conv, UNCLEAR)
    rows = db_session.query(Handoff).filter_by(conversation_id=conv.id).all()
    assert [h.reason for h in rows] == [agent.REASON_UNCLEAR]
    assert rows[0].needs_person is False


def test_tapping_a_chip_answers_the_question(
    db_session: Session, cbe_bank: Bank, conv: Conversation, rewrites: None
) -> None:
    """The whole point. The widget renders each chip as a button whose click
    re-asks that title, so a customer who cannot rephrase answers by
    tapping."""
    first = _turn(db_session, cbe_bank, conv, UNCLEAR)
    tapped = first.suggestions[0]["title"]
    second = _turn(db_session, cbe_bank, conv, tapped)
    assert second.outcome == agent.ANSWERED
    assert second.sources


def test_a_second_failure_stops_asking_and_fetches_a_person(
    db_session: Session, cbe_bank: Bank, conv: Conversation, rewrites: None
) -> None:
    """MAX_CLARIFY_ASKS. Asking twice is an interrogation and a loop — the
    second question is prompted by the same failure as the first."""
    assert _turn(db_session, cbe_bank, conv, UNCLEAR).outcome == agent.CLARIFYING
    second = _turn(db_session, cbe_bank, conv, "zzzz qqqq wwww")
    assert second.outcome == agent.UNANSWERED
    assert second.handoff_created is True
    reasons = [h.reason for h in db_session.query(Handoff).filter_by(conversation_id=conv.id)]
    assert agent.REASON_UNANSWERED in reasons


def test_a_clear_question_is_never_interrupted(
    db_session: Session, cbe_bank: Bank, conv: Conversation
) -> None:
    """The cost of getting this wrong is paid by everybody who types well."""
    for question in ("How do I open a savings account?", "What is the transfer fee?"):
        assert _turn(db_session, cbe_bank, conv, question).outcome == agent.ANSWERED


def test_clarifying_is_not_counted_as_a_question_asked(
    db_session: Session, cbe_bank: Bank, conv: Conversation
) -> None:
    """Out of the analytics denominator, like the contact exchange.

    Counting it would make a customer who is asked "did you mean one of
    these?" and then answered appear twice — quietly deflating the deflection
    rate every time the product does the right thing.
    """
    assert agent.CLARIFYING not in agent.SUBSTANTIVE
    assert agent.CLARIFYING not in agent.RESOLVED


# ------------------------------------------------------- refining


def test_a_rewritten_query_rescues_a_badly_typed_question(
    db_session: Session, cbe_bank: Bank, conv: Conversation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `how open acount` case, end to end.

    The rewrite itself is stubbed — reaching a real Gemini is impossible from
    a sandbox — but everything downstream of it is real: the retry runs
    through the actual `retrieve()` against the actual corpus, and the answer
    comes from whatever that returns.
    """
    monkeypatch.setattr(
        agent, "refine_for_search", lambda _text: "how do I open a savings account"
    )
    result = _turn(db_session, cbe_bank, conv, "how open acount thing zzzz")
    assert result.outcome == agent.ANSWERED
    assert result.sources


def test_the_rewrite_only_moves_the_search_text_never_the_answer(
    db_session: Session, cbe_bank: Bank, conv: Conversation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The doctrine that makes this safe, and the reason it mirrors
    translate_for_search.

    A rewrite that invented a product would still have to survive retrieval,
    the informativeness gate and the model's own decline. So the worst a bad
    rewrite can do is find nothing — the sources always come from real
    documents of this bank.
    """
    monkeypatch.setattr(
        agent,
        "refine_for_search",
        lambda _text: "platinum diaspora gold saver 19 percent guaranteed",
    )
    result = _turn(db_session, cbe_bank, conv, "zzzz qqqq wwww")
    titles = {
        title for (title,) in db_session.query(agent.Document.title).filter_by(bank_id=cbe_bank.id)
    }
    for source in result.sources:
        assert source["title"] in titles
    assert "19 percent" not in result.reply


def test_already_clear_means_the_honest_i_dont_know(
    db_session: Session, cbe_bank: Bank, conv: Conversation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clearly-written question we simply cannot answer must NOT be
    clarified — and this is the case that made the first design wrong.

    "What is your SWIFT code for the Djibouti branch" is well written. Asking
    "did you mean one of these?" blames the customer's typing for our own
    content gap. The sentinel exists so "already fine" and "produced nothing"
    stay distinguishable; an empty string cannot tell them apart.
    """
    calls: list[str] = []

    def _refine(text: str) -> str:
        calls.append(text)
        return llm.NOTHING_TO_REFINE

    monkeypatch.setattr(agent, "refine_for_search", _refine)
    result = _turn(db_session, cbe_bank, conv, UNCLEAR)
    assert calls, "refine should have been attempted on the failure path"
    assert result.outcome == agent.UNANSWERED
    assert result.handoff_created is True
    # The topics are still offered — as an aid, not as a question.
    assert result.suggestions


def test_no_model_configured_falls_back_to_the_old_behaviour_exactly(
    db_session: Session, cbe_bank: Bank, conv: Conversation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Extractive mode is unchanged by this feature, and that is deliberate.

    Both halves need the model: the rewrite obviously, and the clarifying
    question because the rewrite's own verdict is what gates it. With no
    backend configured `refine_for_search` raises, `refined` stays empty, and
    a miss takes precisely the path it took before this change — the honest
    I-don't-know, the topics, the handoff.

    The cost is real and worth stating rather than hiding: a demo with no LLM
    never asks a customer what they meant. The alternative was a rules-only
    guess at "did this person type badly", which is exactly the assumption
    this feature must not make.
    """

    def _boom(_text: str) -> str:
        raise llm.LLMUnavailable("no backend")

    monkeypatch.setattr(agent, "refine_for_search", _boom)
    result = _turn(db_session, cbe_bank, conv, UNCLEAR)
    assert result.outcome == agent.UNANSWERED
    assert result.handoff_created is True
    assert result.suggestions


def test_refining_never_runs_on_a_question_that_was_answered(
    db_session: Session, cbe_bank: Bank, conv: Conversation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure path only. Every answered turn paying for an extra model call
    would be a latency and cost regression on the common case."""
    calls: list[str] = []
    monkeypatch.setattr(
        agent, "refine_for_search", lambda text: calls.append(text) or ""
    )
    assert _turn(db_session, cbe_bank, conv, "How do I open a savings account?").outcome == (
        agent.ANSWERED
    )
    assert calls == []


# ------------------------------------------------------- vocabulary


def test_the_new_outcome_and_reason_are_published() -> None:
    assert agent.REASON_UNCLEAR in agent.HANDOFF_REASONS


def test_the_clarifying_question_exists_in_all_six_languages() -> None:
    from bankassist.i18n import t

    asked = {t(lang, "clarify_intro") for lang in ("en", "am", "om", "ti", "so", "sw")}
    assert len(asked) == 6, "a language is falling back to another's wording"
    assert all(text.strip() for text in asked)
