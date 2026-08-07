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
from .llm import LLMUnavailable, generate_answer
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
        result = ChatResult(t(language, "greeting", bank=bank.name), intent, language)
    elif intent == classifier.ACCOUNT_SPECIFIC:
        result = ChatResult(t(language, "account_help"), intent, language)
    elif intent == classifier.COMPLAINT:
        _create_handoff(db, bank, conversation, "complaint", text[:2000])
        result = ChatResult(t(language, "complaint_ack"), intent, language, handoff_created=True)
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
        if not chunks:
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
            reply = _answer_from_knowledge(bank, query, chunks, language)
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
