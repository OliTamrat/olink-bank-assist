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

from sqlalchemy.orm import Session

from . import classifier
from .i18n import t
from .llm import LLMUnavailable, generate_answer
from .logging_config import log_event
from .models import AuditLog, Bank, Conversation, Handoff, Message
from .retrieval import RetrievedChunk, retrieve

logger = logging.getLogger(__name__)

MAX_FALLBACK_CHUNKS = 2


@dataclass
class ChatResult:
    reply: str
    intent: str
    language: str
    handoff_created: bool = False
    sources: list[dict[str, Any]] = field(default_factory=list)


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

    intent = classifier.classify_intent(text)
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
    else:
        chunks = retrieve(db, bank.id, text)
        if not chunks:
            _create_handoff(db, bank, conversation, "unanswered_question", text[:2000])
            reply = t(language, "unknown")
            # The disclaimer is triggered by intent (a regex match, decided
            # before retrieval ever runs), not by whether specific content
            # was found — it must never be skippable just because a pressure
            # or padded phrasing dodged the knowledge base too.
            if intent == classifier.INVESTMENT_ADVICE:
                reply = f"{reply}\n\n{t(language, 'advice_disclaimer')}"
            result = ChatResult(reply, intent, language, handoff_created=True)
        else:
            reply = _answer_from_knowledge(bank, text, chunks, language)
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
