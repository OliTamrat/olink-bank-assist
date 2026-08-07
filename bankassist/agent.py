"""Conversation orchestration: classify -> guardrails -> retrieve -> answer.

Safety doctrine (mirrors the dispatch agents):
- Tool output is truth: answers come from retrieved knowledge-base content
  or fixed templates — never from model free association.
- Allowlist, not blocklist: only greeting/question/investment-education
  intents are answered autonomously. Account-specific and complaint traffic
  goes to the human path.
- Investment questions always carry the education-not-advice disclaimer.
- An unanswerable question creates a Handoff row so the bank sees every gap.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import classifier
from .i18n import t
from .llm import (
    LLMDeclined,
    LLMUnavailable,
    answer_from_general_knowledge,
    generate_answer,
    translate_for_search,
)
from .logging_config import log_event
from .models import AuditLog, Bank, Conversation, Document, Handoff, Message
from .retrieval import RetrievedChunk, retrieve, suggest_topics

logger = logging.getLogger(__name__)

MAX_FALLBACK_CHUNKS = 2

# How many times one conversation may be asked for contact details before we
# take the silence as an answer. Each handoff is its own promise of a
# callback, so a second unanswered question earns a second ask — a third is
# pestering someone who has already declined twice.
MAX_CONTACT_ASKS = 2

# A document tagged with this category is this bank's confident, positive
# answer to "why should I choose you over another bank?" — looked up
# directly, not via the fuzzy BM25 scorer. A comparison question names a
# competitor, which by design never appears in this bank's own content, so
# ordinary retrieval on the user's raw text can't find it; the intent match
# (classifier.COMPARISON) already tells us what's being asked. A tenant
# without one of these documents gets the generic redirect template instead
# of a handoff — never silence, and never a claim about the competitor.
WHY_CHOOSE_CATEGORY = "why-choose-us"

# What the assistant did on a turn, written to Message.outcome and grouped by
# the analytics endpoint. Deliberately a small, stable vocabulary: these names
# end up in front of a bank as the report on whether the product works, so
# adding one is a product decision, not a refactor.
ANSWERED = "answered"                    # from this bank's own content
GENERAL_GUIDANCE = "general_guidance"    # universal banking, carries no sources
UNANSWERED = "unanswered"                # nothing found — a content gap
COMPLAINT = "complaint"                  # routed to a person
ACCOUNT_BLOCKED = "account_blocked"      # security template; no account access
COMPARISON = "comparison"                # "is X better than you?"
GREETING = "greeting"                    # hello, not a question
CONTACT_CAPTURED = "contact_captured"    # the customer left a number

# Turns that represent a customer actually asking this bank something. The
# denominator of every rate below, so greetings and the contact exchange can't
# quietly inflate the numbers a bank is being sold on.
SUBSTANTIVE = (ANSWERED, GENERAL_GUIDANCE, UNANSWERED, COMPLAINT, ACCOUNT_BLOCKED, COMPARISON)

# Substantive turns that did NOT need a person. account_blocked belongs here:
# refusing to read out an account balance in chat is the assistant working
# correctly, and it files no handoff.
RESOLVED = (ANSWERED, GENERAL_GUIDANCE, ACCOUNT_BLOCKED, COMPARISON)


def _bank_aliases(bank: Bank) -> tuple[str, ...]:
    return tuple({alias for alias in (bank.slug, bank.name) if alias})


@dataclass
class ChatResult:
    reply: str
    intent: str
    language: str
    handoff_created: bool = False
    sources: list[dict[str, Any]] = field(default_factory=list)
    # Topics offered when nothing confident was found. Real document titles
    # from this bank only — see retrieval.suggest_topics.
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    # True when the reply is universally-standard banking guidance rather than
    # this bank's own published content. Surfaced so it is never mistaken for
    # the bank speaking.
    general_knowledge: bool = False
    # True when the reply just asked how to reach this customer. Lets a channel
    # prompt for it — the widget swaps the input placeholder — instead of
    # leaving the ask to be read past.
    awaiting_contact: bool = False
    # What this turn did. Required and keyword-only on purpose: a default would
    # let a new branch ship unclassified and quietly skew every metric built on
    # it, which is the failure mode analytics can least afford.
    outcome: str = field(kw_only=True)


def _extractive_answer(bank: Bank, chunks: list[RetrievedChunk], language: str) -> str:
    intro = t(language, "fallback_intro", bank=bank.name)
    body = "\n\n".join(c.text for c in chunks[:MAX_FALLBACK_CHUNKS])
    return f"{intro}\n\n{body}"


def _answer_from_knowledge(
    bank: Bank, question: str, chunks: list[RetrievedChunk], language: str
) -> str:
    try:
        return generate_answer(question, chunks, language, bank.name)
    except LLMUnavailable:
        return _extractive_answer(bank, chunks, language)


def _create_handoff(
    db: Session, bank: Bank, conversation: Conversation, reason: str, detail: str
) -> None:
    handoff = Handoff(
        bank_id=bank.id,
        conversation_id=conversation.id,
        reason=reason,
        detail=detail,
        # Snapshot whatever we already know, so an operator working the queue
        # sees who to call without joining back to the conversation. Usually
        # null at this point — we only ask for contact details once a handoff
        # exists — and _capture_contact backfills the open rows afterwards.
        contact_name=conversation.customer_name,
        contact_phone=conversation.contact_phone,
    )
    db.add(handoff)
    db.flush()
    db.add(
        AuditLog(
            bank_id=bank.id,
            actor="agent",
            action="handoff_created",
            entity_type="handoff",
            entity_id=str(handoff.id),
            log_metadata={"reason": reason, "conversation_id": str(conversation.id)},
        )
    )


def _request_contact(
    db: Session, bank: Bank, conversation: Conversation, language: str, reply: str
) -> str:
    """Append the contact request, unless asking again would be nagging.

    Skipped once we can already reach them — being asked for your number twice
    reads as nobody being on the other end, which is the opposite of the
    reassurance a handoff is meant to give.

    Also capped. Each handoff is a separate promise of a callback, so a second
    unanswered question does earn a second ask; a customer who has ignored two
    of them has answered, and a third is pestering. The count comes from the
    handoffs themselves rather than a column, so it cannot drift out of step
    with them.
    """
    if conversation.contact_phone:
        return reply
    asks = db.execute(
        select(func.count())
        .select_from(Handoff)
        .where(
            Handoff.bank_id == bank.id,
            Handoff.conversation_id == conversation.id,
            Handoff.contact_phone.is_(None),
        )
    ).scalar_one()
    if asks > MAX_CONTACT_ASKS:
        conversation.awaiting_contact = False
        return reply
    conversation.awaiting_contact = True
    return f"{reply}\n\n{t(language, 'ask_contact')}"


def _capture_contact(
    db: Session, bank: Bank, conversation: Conversation, text: str, language: str
) -> ChatResult | None:
    """Store contact details offered in reply to the request, or give up on them.

    Returns None when the message was not contact details at all. That is a
    normal outcome: the customer changed the subject, and the caller answers
    the new message rather than asking again.
    """
    conversation.awaiting_contact = False
    name, contact = classifier.extract_contact(text)
    if name and not conversation.customer_name:
        conversation.customer_name = name[:80]
    if not contact:
        return None

    conversation.contact_phone = contact[:40]
    # Backfill the handoffs this customer is actually waiting on. Closed ones
    # are left alone: an operator has already dealt with them, and rewriting a
    # resolved record to add a number nobody used only muddies the audit trail.
    open_handoffs = db.execute(
        select(Handoff).where(
            Handoff.bank_id == bank.id,
            Handoff.conversation_id == conversation.id,
            Handoff.status == "open",
        )
    ).scalars().all()
    for handoff in open_handoffs:
        handoff.contact_phone = conversation.contact_phone
        handoff.contact_name = conversation.customer_name
    db.add(
        AuditLog(
            bank_id=bank.id,
            actor="agent",
            action="contact_captured",
            entity_type="conversation",
            entity_id=str(conversation.id),
            # The number itself is personal data and stays out of the audit
            # trail; that it was captured, and onto how many open handoffs, is
            # what an auditor needs.
            log_metadata={"handoffs_updated": len(open_handoffs)},
        )
    )

    key = "contact_saved_named" if conversation.customer_name else "contact_saved"
    reply = t(
        language,
        key,
        contact=conversation.contact_phone,
        # contact_saved has no {name} placeholder, so the empty string is only
        # ever formatted into a template that ignores it.
        name=conversation.customer_name or "",
    )
    return ChatResult(reply, classifier.QUESTION, language, outcome=CONTACT_CAPTURED)


def handle_message(
    db: Session, bank: Bank, conversation: Conversation, text: str
) -> ChatResult:
    started = time.perf_counter()
    detected = classifier.detect_language(text)
    language = detected or conversation.language or bank.default_language
    conversation.language = language

    # A volunteered name sticks for the rest of the conversation — being
    # asked your name twice is worse than never being asked. Only ever set
    # from an explicit self-introduction, and never logged.
    introduced = classifier.extract_name(text)
    if introduced and not conversation.customer_name:
        conversation.customer_name = introduced[:80]
    name = conversation.customer_name

    intent = classifier.classify_intent(text, bank_aliases=_bank_aliases(bank))
    # Held so the turn's outcome can be stamped on it once known. Both rows of
    # a turn carry the same outcome, which is what lets analytics ask "which
    # customer messages were real questions?" exactly instead of guessing from
    # intent — and intent guesses badly here: a reply of "Oli 0911234567"
    # classifies as an ordinary question, and ranked topics by intent put a
    # customer's name and phone number in the report.
    user_message = Message(
        conversation_id=conversation.id,
        bank_id=bank.id,
        role="user",
        text=text,
        intent=intent,
    )
    db.add(user_message)

    result: ChatResult
    # The customer was just asked how to reach them. Try to read this message
    # as the answer before anything else — a phone number classifies as
    # nothing useful, and running it through retrieval would produce an
    # "I don't have information about that" reply to details we asked for.
    captured = None
    if conversation.awaiting_contact:
        captured = _capture_contact(db, bank, conversation, text, language)
        name = conversation.customer_name
    if captured is not None:
        result = captured
    elif intent == classifier.GREETING:
        greeting = (
            t(language, "greeting_named", bank=bank.name, name=name)
            if name
            else t(language, "greeting", bank=bank.name)
        )
        result = ChatResult(greeting, intent, language, outcome=GREETING)
    elif intent == classifier.ACCOUNT_SPECIFIC:
        result = ChatResult(t(language, "account_help"), intent, language, outcome=ACCOUNT_BLOCKED)
    elif intent == classifier.COMPLAINT:
        _create_handoff(db, bank, conversation, "complaint", text[:2000])
        ack = t(language, "complaint_ack")
        if name:
            ack = f"{t(language, 'ack_named', name=name)} {ack}"
        ack = _request_contact(db, bank, conversation, language, ack)
        result = ChatResult(
            ack,
            intent,
            language,
            handoff_created=True,
            awaiting_contact=conversation.awaiting_contact,
            outcome=COMPLAINT,
        )
    elif intent == classifier.COMPARISON:
        why_choose = db.execute(
            select(Document).where(
                Document.bank_id == bank.id, Document.category == WHY_CHOOSE_CATEGORY
            )
        ).scalars().first()
        if why_choose is None:
            reply = t(language, "comparison_fallback", bank=bank.name)
            result = ChatResult(reply, intent, language, outcome=COMPARISON)
        else:
            reply = f"{t(language, 'comparison_intro', bank=bank.name)}\n\n{why_choose.content}"
            sources = [{"document_id": why_choose.id, "title": why_choose.title}]
            result = ChatResult(reply, intent, language, sources=sources, outcome=COMPARISON)
    else:
        # Search the question, not the hello. Greeting words are ordinary
        # content words to BM25, so leaving them in pads the query's
        # content-word count and raises the informativeness bar in
        # retrieve() — which made "Selam, how do I open an account?" harder
        # to answer than the same question asked bluntly.
        query, _greeted = classifier.strip_greeting(text)
        query = query or text
        chunks = retrieve(db, bank.id, query)

        # Lexical retrieval cannot match across languages — "liqii" and
        # "loan" share no characters — so an Afaan Oromo, Somali or Tigrinya
        # question found nothing at all in a mostly-English knowledge base,
        # no matter how well the bank had written it. Retry once with the
        # question rendered as an English search query.
        #
        # Only the search text is translated: the answer is still generated
        # from the retrieved documents in the customer's own language, and
        # the informativeness gate still decides whether anything was really
        # found. A bad translation therefore costs a miss, never a wrong
        # answer. Runs only on the miss path, so the common case pays
        # nothing for it.
        if not chunks and language != "en":
            try:
                english = translate_for_search(query)
            except LLMUnavailable:
                english = ""
            if english and english.lower() != query.lower():
                translated_hits = retrieve(db, bank.id, english)
                if translated_hits:
                    chunks = translated_hits
                    query = english

        # Retrieval finding something is not the same as that something
        # answering the question. The model reads the retrieved text and can
        # decline — Awash's only ATM document covers fraud safety, which
        # does not explain how to use an ATM. A decline has to land in the
        # miss path: shipping it as an answer attached a source chip to a
        # non-answer, offered the customer nothing further, and filed no
        # handoff, so the bank never learned the content was missing.
        answer: str | None = None
        if chunks:
            try:
                answer = _answer_from_knowledge(bank, query, chunks, language)
            except LLMDeclined:
                answer = None

        # Nothing in this bank's content answers the question. Some questions
        # do not need bank content at all: ATM mechanics are identical on every
        # machine on earth, and an assistant that cannot explain what a PIN is
        # looks broken on exactly the questions a first-time customer asks. The
        # model may answer those from general knowledge, and must decline the
        # moment an answer would need a figure, a limit, a requirement or
        # anything specific to this bank — see llm.answer_from_general_knowledge.
        general: str | None = None
        if answer is None and bank.allow_general_knowledge:
            try:
                general = answer_from_general_knowledge(query, language, bank.name)
            except (LLMDeclined, LLMUnavailable):
                general = None

        if general is not None:
            # Labelled, and carrying no sources, because it genuinely came from
            # none. Still filed as a handoff: the bank should see that customers
            # ask this and that it has no content of its own, which is exactly
            # the prompt to write some.
            _create_handoff(
                db, bank, conversation, "answered_from_general_knowledge", text[:2000]
            )
            reply = f"{general}\n\n{t(language, 'general_guidance', bank=bank.name)}"
            result = ChatResult(
                reply,
                intent,
                language,
                handoff_created=True,
                general_knowledge=True,
                outcome=GENERAL_GUIDANCE,
            )
        elif answer is None:
            _create_handoff(db, bank, conversation, "unanswered_question", text[:2000])
            reply = t(language, "unknown")
            # Retrieval is lexical, so a customer who phrases a question
            # differently from the knowledge base gets nothing — and most
            # people will not rephrase to match a corpus they can't see.
            # Rather than loosening the informativeness gate (which is what
            # stops confidently-wrong answers), offer the near misses as
            # topics. These are real document titles, so this can't invent
            # a product or figure; the handoff is still filed either way,
            # so a genuine knowledge gap stays visible to the bank.
            suggestions = [
                {"document_id": s.document_id, "title": s.title}
                for s in suggest_topics(db, bank.id, query)
            ]
            # Contact first, alternatives second. The other order is what a
            # customer reported as the assistant changing the subject: it
            # promised a person would follow up, then immediately offered
            # unrelated topics, and never collected any way to follow up on.
            # Handle the concern, then offer alternatives.
            reply = _request_contact(db, bank, conversation, language, reply)
            if suggestions:
                reply = f"{reply}\n\n{t(language, 'did_you_mean')}"
            # The disclaimer is triggered by intent (a regex match, decided
            # before retrieval ever runs), not by whether specific content
            # was found — it must never be skippable just because a pressure
            # or padded phrasing dodged the knowledge base too.
            if intent == classifier.INVESTMENT_ADVICE:
                reply = f"{reply}\n\n{t(language, 'advice_disclaimer')}"
            result = ChatResult(
                reply,
                intent,
                language,
                handoff_created=True,
                suggestions=suggestions,
                awaiting_contact=conversation.awaiting_contact,
                outcome=UNANSWERED,
            )
        else:
            reply = answer
            if intent == classifier.INVESTMENT_ADVICE:
                reply = f"{reply}\n\n{t(language, 'advice_disclaimer')}"
            sources = [
                {"document_id": c.document_id, "title": c.title} for c in chunks
            ]
            deduped = list({s["document_id"]: s for s in sources}.values())
            result = ChatResult(reply, intent, language, sources=deduped, outcome=ANSWERED)

    user_message.outcome = result.outcome
    db.add(
        Message(
            conversation_id=conversation.id,
            bank_id=bank.id,
            role="assistant",
            text=result.reply,
            intent=intent,
            sources=result.sources or None,
            outcome=result.outcome,
        )
    )
    db.commit()
    # Metadata only — chat text is personal data and must never be logged.
    log_event(
        logger,
        "chat_handled",
        bank=bank.slug,
        channel=conversation.channel,
        intent=intent,
        language=result.language,
        handoff=result.handoff_created,
        sources=len(result.sources),
        outcome=result.outcome,
        # Whether we now have a way to reach this customer — never the number
        # itself, which is personal data exactly like the chat text.
        reachable=bool(conversation.contact_phone),
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return result
