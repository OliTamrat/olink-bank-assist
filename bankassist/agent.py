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

from sqlalchemy import select
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

# A document tagged with this category is this bank's confident, positive
# answer to "why should I choose you over another bank?" — looked up
# directly, not via the fuzzy BM25 scorer. A comparison question names a
# competitor, which by design never appears in this bank's own content, so
# ordinary retrieval on the user's raw text can't find it; the intent match
# (classifier.COMPARISON) already tells us what's being asked. A tenant
# without one of these documents gets the generic redirect template instead
# of a handoff — never silence, and never a claim about the competitor.
WHY_CHOOSE_CATEGORY = "why-choose-us"


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
        bank_id=bank.id, conversation_id=conversation.id, reason=reason, detail=detail
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
    db.add(
        Message(
            conversation_id=conversation.id,
            bank_id=bank.id,
            role="user",
            text=text,
            intent=intent,
        )
    )

    result: ChatResult
    if intent == classifier.GREETING:
        greeting = (
            t(language, "greeting_named", bank=bank.name, name=name)
            if name
            else t(language, "greeting", bank=bank.name)
        )
        result = ChatResult(greeting, intent, language)
    elif intent == classifier.ACCOUNT_SPECIFIC:
        result = ChatResult(t(language, "account_help"), intent, language)
    elif intent == classifier.COMPLAINT:
        _create_handoff(db, bank, conversation, "complaint", text[:2000])
        ack = t(language, "complaint_ack")
        if name:
            ack = f"{t(language, 'ack_named', name=name)} {ack}"
        result = ChatResult(ack, intent, language, handoff_created=True)
    elif intent == classifier.COMPARISON:
        why_choose = db.execute(
            select(Document).where(
                Document.bank_id == bank.id, Document.category == WHY_CHOOSE_CATEGORY
            )
        ).scalars().first()
        if why_choose is None:
            reply = t(language, "comparison_fallback", bank=bank.name)
            result = ChatResult(reply, intent, language)
        else:
            reply = f"{t(language, 'comparison_intro', bank=bank.name)}\n\n{why_choose.content}"
            sources = [{"document_id": why_choose.id, "title": why_choose.title}]
            result = ChatResult(reply, intent, language, sources=sources)
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
                reply, intent, language, handoff_created=True, general_knowledge=True
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
            if suggestions:
                reply = f"{reply}\n\n{t(language, 'did_you_mean')}"
            # The disclaimer is triggered by intent (a regex match, decided
            # before retrieval ever runs), not by whether specific content
            # was found — it must never be skippable just because a pressure
            # or padded phrasing dodged the knowledge base too.
            if intent == classifier.INVESTMENT_ADVICE:
                reply = f"{reply}\n\n{t(language, 'advice_disclaimer')}"
            result = ChatResult(
                reply, intent, language, handoff_created=True, suggestions=suggestions
            )
        else:
            reply = answer
            if intent == classifier.INVESTMENT_ADVICE:
                reply = f"{reply}\n\n{t(language, 'advice_disclaimer')}"
            sources = [
                {"document_id": c.document_id, "title": c.title} for c in chunks
            ]
            deduped = list({s["document_id"]: s for s in sources}.values())
            result = ChatResult(reply, intent, language, sources=deduped)

    db.add(
        Message(
            conversation_id=conversation.id,
            bank_id=bank.id,
            role="assistant",
            text=result.reply,
            intent=intent,
            sources=result.sources or None,
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
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return result
