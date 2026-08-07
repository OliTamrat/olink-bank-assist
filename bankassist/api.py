from __future__ import annotations

import hmac
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import agent as agent_module
from . import telegram
from .agent import handle_message
from .classifier import redact_contact
from .config import get_settings
from .db import get_db, init_db
from .i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES
from .llm import active_backend, credentials_ready
from .logging_config import configure_logging, log_event
from .models import AuditLog, Bank, Conversation, Document, Handoff, Message, new_token
from .ratelimit import SlidingWindowLimiter
from .retrieval import content_signature, reindex_document

logger = logging.getLogger(__name__)

_STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    app.state.ip_limiter = SlidingWindowLimiter(settings.chat_rate_per_ip)
    app.state.conversation_limiter = SlidingWindowLimiter(settings.chat_rate_per_conversation)
    yield


app = FastAPI(title="Olink Bank Assist", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # the widget is embedded on bank websites
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _access_log(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    if request.url.path != "/health":
        log_event(
            logger,
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    return response


# ---------------------------------------------------------------- helpers


def _get_bank(db: Session, slug: str) -> Bank:
    bank = db.execute(select(Bank).where(Bank.slug == slug)).scalar_one_or_none()
    if bank is None:
        raise HTTPException(status_code=404, detail="Unknown bank")
    return bank


def require_admin(
    slug: str,
    x_admin_token: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Bank:
    bank = _get_bank(db, slug)
    if not x_admin_token or not hmac.compare_digest(x_admin_token, bank.admin_token):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return bank


def _audit(db: Session, bank: Bank, action: str, entity_type: str, entity_id: str,
           metadata: dict[str, Any] | None = None) -> None:
    db.add(
        AuditLog(
            bank_id=bank.id,
            actor="admin",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            log_metadata=metadata,
        )
    )


# ---------------------------------------------------------------- schemas


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    language: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    intent: str
    language: str
    handoff_created: bool
    sources: list[dict[str, Any]]
    suggestions: list[dict[str, Any]] = []
    # True when the reply is universally-standard banking guidance rather than
    # this bank's own published content.
    general_knowledge: bool = False
    # The reply asked how to reach this customer; the next message is expected
    # to be their name and number. Channels use it to prompt for exactly that.
    awaiting_contact: bool = False


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    category: str = "general"
    language: str = "en"


class DocumentBulkIn(BaseModel):
    documents: list[DocumentIn] = Field(min_length=1, max_length=200)


class HealthOut(BaseModel):
    status: str
    llm: str
    # Whether the configured backend can actually authenticate. A backend can
    # be configured correctly and still never run — that exact silent
    # fallback shipped once — so this makes it checkable from outside without
    # reading Cloud Run logs. A boolean only: no error text in a public route.
    llm_ready: bool = False
    # Short sha of the commit this instance is running. Empty when unset (local
    # dev, or a deploy that didn't pass it). Exists because a merged commit can
    # silently fail to deploy — the workflow_run trigger did not fire once —
    # and without this, answering "is main actually live?" meant reading
    # GitHub Actions history instead of making one request.
    revision: str = ""


# ---------------------------------------------------------------- public


# A cached diagnostic is worse than none: /health exists to answer "what is
# running right now", and a stale copy answers it wrong with full confidence.
# Hit once during a deploy, a cached response keeps reporting the old build's
# fields long after the new revision is serving.
@app.get("/health", response_model=HealthOut)
def health(response: Response) -> HealthOut:
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return HealthOut(
        status="ok",
        llm=active_backend(),
        llm_ready=credentials_ready(),
        revision=get_settings().git_sha[:7],
    )


@app.get("/banks/{slug}/public")
def bank_public(slug: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    bank = _get_bank(db, slug)
    return {
        "name": bank.name,
        "slug": bank.slug,
        "primary_color": bank.primary_color,
        "logo_url": bank.logo_url,
        "default_language": bank.default_language,
        "disclaimer": bank.disclaimer,
        "languages": [
            {"code": code, "name": LANGUAGE_NAMES[code]} for code in SUPPORTED_LANGUAGES
        ],
    }


@app.post("/chat/{slug}", response_model=ChatResponse)
def chat(
    slug: str, payload: ChatRequest, request: Request, db: Session = Depends(get_db)
) -> ChatResponse:
    client_ip = request.client.host if request.client else "unknown"
    ip_limiter: SlidingWindowLimiter = request.app.state.ip_limiter
    if not ip_limiter.allow(f"{slug}:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many requests, please slow down")
    conversation_limiter: SlidingWindowLimiter = request.app.state.conversation_limiter
    if payload.conversation_id and not conversation_limiter.allow(payload.conversation_id):
        raise HTTPException(status_code=429, detail="Too many requests, please slow down")

    bank = _get_bank(db, slug)
    conversation: Conversation | None = None
    if payload.conversation_id:
        conversation = db.get(Conversation, payload.conversation_id)
        # Tenancy: a conversation id from another bank must not be resumable here.
        if conversation is not None and conversation.bank_id != bank.id:
            raise HTTPException(status_code=404, detail="Unknown conversation")
    if conversation is None:
        conversation = Conversation(bank_id=bank.id, channel="web")
        db.add(conversation)
        db.flush()
    if payload.language in SUPPORTED_LANGUAGES:
        conversation.language = payload.language

    result = handle_message(db, bank, conversation, payload.message)
    return ChatResponse(
        conversation_id=conversation.id,
        reply=result.reply,
        intent=result.intent,
        language=result.language,
        handoff_created=result.handoff_created,
        sources=result.sources,
        suggestions=result.suggestions,
        general_knowledge=result.general_knowledge,
        awaiting_contact=result.awaiting_contact,
    )


# Both pages are single files with their CSS and JS inlined, so a cached
# copy pins the *entire* UI — after a deploy a returning visitor keeps
# seeing the old widget with no way to tell, which is exactly what happened
# after the capability-chip redesign shipped. There is no hashed-asset
# filename to bust here, so the HTML itself must not be cached. These are
# tiny documents served on a cold open; revalidating costs nothing next to
# demoing a stale UI to a prospect.
_NO_STORE = {"Cache-Control": "no-store, must-revalidate"}


@app.get("/widget")
def widget_page() -> FileResponse:
    return FileResponse(_STATIC / "widget.html", media_type="text/html", headers=_NO_STORE)


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(_STATIC / "admin.html", media_type="text/html", headers=_NO_STORE)


# ---------------------------------------------------------------- telegram


@app.post("/webhooks/telegram/{slug}")
async def telegram_webhook(
    slug: str, request: Request, db: Session = Depends(get_db)
) -> dict[str, bool]:
    bank = _get_bank(db, slug)
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not bank.telegram_webhook_secret or not hmac.compare_digest(
        secret, bank.telegram_webhook_secret
    ):
        raise HTTPException(status_code=403, detail="Bad webhook secret")

    update = await request.json()
    message = update.get("message") or {}
    text = message.get("text")
    chat_info = message.get("chat") or {}
    chat_id = chat_info.get("id")
    if not text or chat_id is None:
        return {"ok": True}  # ignore non-text updates

    external_id = str(chat_id)
    conversation = db.execute(
        select(Conversation).where(
            Conversation.bank_id == bank.id,
            Conversation.channel == "telegram",
            Conversation.external_user_id == external_id,
        )
    ).scalar_one_or_none()
    if conversation is None:
        conversation = Conversation(
            bank_id=bank.id, channel="telegram", external_user_id=external_id
        )
        db.add(conversation)
        db.flush()

    result = handle_message(db, bank, conversation, text)
    if bank.telegram_bot_token:
        telegram.send_message(bank.telegram_bot_token, chat_id, result.reply)
    return {"ok": True}


class TelegramConnectIn(BaseModel):
    bot_token: str = Field(min_length=10)


@app.post("/admin/api/{slug}/telegram/connect")
def telegram_connect(
    slug: str, payload: TelegramConnectIn,
    bank: Bank = Depends(require_admin), db: Session = Depends(get_db),
) -> dict[str, Any]:
    bank.telegram_bot_token = payload.bot_token
    bank.telegram_webhook_secret = new_token()
    webhook_url = f"{get_settings().app_base_url}/webhooks/telegram/{bank.slug}"
    response = telegram.set_webhook(payload.bot_token, webhook_url, bank.telegram_webhook_secret)
    _audit(db, bank, "telegram_connected", "bank", bank.id, {"webhook_url": webhook_url})
    db.commit()
    return {"webhook_url": webhook_url, "telegram_response": response}


# ---------------------------------------------------------------- admin: documents


@app.get("/admin/api/{slug}/documents")
def list_documents(
    bank: Bank = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    docs = db.execute(
        select(Document).where(Document.bank_id == bank.id).order_by(Document.updated_at.desc())
    ).scalars().all()
    return [
        {
            "id": d.id, "title": d.title, "category": d.category,
            "language": d.language, "updated_at": d.updated_at.isoformat(),
            "content": d.content,
        }
        for d in docs
    ]


@app.post("/admin/api/{slug}/documents", status_code=201)
def create_document(
    payload: DocumentIn, bank: Bank = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    doc = Document(
        bank_id=bank.id, title=payload.title, content=payload.content,
        category=payload.category, language=payload.language,
    )
    db.add(doc)
    db.flush()
    n_chunks = reindex_document(db, doc)
    _audit(db, bank, "document_created", "document", doc.id, {"chunks": n_chunks})
    db.commit()
    return {"id": doc.id, "chunks": n_chunks}


@app.post("/admin/api/{slug}/documents/bulk", status_code=201)
def bulk_create_documents(
    payload: DocumentBulkIn, bank: Bank = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    # All-or-nothing: reject the whole batch on any bad language code rather than
    # importing a partial knowledge base and leaving the admin to spot which rows
    # silently failed. This is the onboarding path for a bank's real KB, where a
    # dozens-of-documents batch getting half-imported is worse than getting none.
    bad = [
        {"index": i, "title": d.title, "language": d.language}
        for i, d in enumerate(payload.documents)
        if d.language not in SUPPORTED_LANGUAGES
    ]
    if bad:
        raise HTTPException(
            status_code=422,
            detail={"error": "Unsupported language code", "invalid_documents": bad},
        )

    created: list[Document] = []
    for item in payload.documents:
        doc = Document(
            bank_id=bank.id, title=item.title, content=item.content,
            category=item.category, language=item.language,
        )
        db.add(doc)
        created.append(doc)
    db.flush()
    total_chunks = sum(reindex_document(db, doc) for doc in created)
    _audit(
        db, bank, "documents_bulk_imported", "document", "bulk",
        {"count": len(created), "chunks": total_chunks},
    )
    db.commit()
    return {"created": len(created), "ids": [d.id for d in created]}


@app.put("/admin/api/{slug}/documents/{document_id}")
def update_document(
    document_id: str, payload: DocumentIn,
    bank: Bank = Depends(require_admin), db: Session = Depends(get_db),
) -> dict[str, Any]:
    doc = db.get(Document, document_id)
    if doc is None or doc.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown document")
    doc.title, doc.content = payload.title, payload.content
    doc.category, doc.language = payload.category, payload.language
    n_chunks = reindex_document(db, doc)
    _audit(db, bank, "document_updated", "document", doc.id, {"chunks": n_chunks})
    db.commit()
    return {"id": doc.id, "chunks": n_chunks}


@app.delete("/admin/api/{slug}/documents/{document_id}", status_code=204)
def delete_document(
    document_id: str, bank: Bank = Depends(require_admin), db: Session = Depends(get_db)
) -> None:
    doc = db.get(Document, document_id)
    if doc is None or doc.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown document")
    _audit(db, bank, "document_deleted", "document", doc.id, {"title": doc.title})
    db.delete(doc)
    db.commit()


# ---------------------------------------------------------------- admin: conversations & handoffs


@app.get("/admin/api/{slug}/conversations")
def list_conversations(
    bank: Bank = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    convos = db.execute(
        select(Conversation).where(Conversation.bank_id == bank.id)
        .order_by(Conversation.created_at.desc()).limit(100)
    ).scalars().all()
    return [
        {
            "id": c.id, "channel": c.channel, "language": c.language,
            "created_at": c.created_at.isoformat(),
        }
        for c in convos
    ]


@app.get("/admin/api/{slug}/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: str, bank: Bank = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    convo = db.get(Conversation, conversation_id)
    if convo is None or convo.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown conversation")
    msgs = db.execute(
        select(Message).where(Message.conversation_id == convo.id).order_by(Message.created_at)
    ).scalars().all()
    return [
        {
            "role": m.role, "text": m.text, "intent": m.intent,
            "sources": m.sources, "created_at": m.created_at.isoformat(),
        }
        for m in msgs
    ]


@app.get("/admin/api/{slug}/handoffs")
def list_handoffs(
    bank: Bank = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Handoff)
        .where(Handoff.bank_id == bank.id)
        .order_by(Handoff.created_at.desc())
        .limit(200)
    ).scalars().all()
    return [
        {
            "id": h.id, "reason": h.reason, "detail": h.detail, "status": h.status,
            "conversation_id": h.conversation_id, "created_at": h.created_at.isoformat(),
            # Who to call. The whole point of a handoff queue is that someone
            # works it, and until now a row said a customer wanted a callback
            # without saying where to.
            "contact_name": h.contact_name, "contact_phone": h.contact_phone,
        }
        for h in rows
    ]


@app.get("/admin/api/{slug}/content-gaps")
def content_gaps(
    bank: Bank = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """What customers ask that this bank has no content for, ranked.

    Every gap already files a handoff carrying the customer's own words, but
    as individual rows that is a pile, not a work queue. Grouped and ranked by
    frequency it becomes the one artifact a bank cannot get anywhere else: a
    list of what its customers actually ask and nobody can answer.

    Two reasons are distinguished because they need different work:
    unanswered_question means nothing was found at all, while
    answered_from_general_knowledge means the assistant fell back to
    universal banking guidance — the bank may want to own that answer in its
    own words, with its own limits and fees.
    """
    rows = db.execute(
        select(Handoff)
        .where(Handoff.bank_id == bank.id)
        .where(Handoff.reason.in_(["unanswered_question", "answered_from_general_knowledge"]))
        .order_by(Handoff.created_at.desc())
        .limit(1000)
    ).scalars().all()

    grouped: dict[str, dict[str, Any]] = {}
    for h in rows:
        # Same scrubbing as the analytics report, and for the same reason:
        # this is an aggregate view that gets exported. The handoff row itself
        # still carries the exact words and the contact fields, which is what
        # an operator returning the call actually needs.
        question = redact_contact((h.detail or "").strip())
        if not question:
            continue
        key = content_signature(question) or question.lower()
        gap = grouped.setdefault(
            key,
            {
                "signature": key,
                "count": 0,
                "open_count": 0,
                "reasons": {},
                "examples": [],
                "last_asked": h.created_at.isoformat(),
            },
        )
        gap["count"] += 1
        if h.status == "open":
            gap["open_count"] += 1
        gap["reasons"][h.reason] = gap["reasons"].get(h.reason, 0) + 1
        # Rows arrive newest-first, so the first example is the latest wording.
        if question not in gap["examples"] and len(gap["examples"]) < 3:
            gap["examples"].append(question)

    ranked = sorted(grouped.values(), key=lambda g: (-g["count"], g["signature"]))
    return ranked[:50]


# How far back the dashboard looks by default. A month is long enough to show a
# trend and short enough that "is it working *now*" isn't diluted by the first
# week of a pilot, when the knowledge base is still being filled in.
DEFAULT_ANALYTICS_DAYS = 30
MAX_TOP_TOPICS = 15


@app.get("/admin/api/{slug}/analytics")
def analytics(
    days: int = DEFAULT_ANALYTICS_DAYS,
    bank: Bank = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """What this assistant did, in the terms a bank decides renewal on.

    Content Gaps answers "what should we write next". This answers the prior
    question — "is it working at all" — and the two are deliberately different
    reports: a bank that only ever sees its failures will conclude the product
    is failing.

    Every rate here is reported alongside the counts it came from, and any
    rate whose denominator is zero is returned as null rather than 0. A fresh
    tenant showing "0% deflection" would be a lie told by a division.
    """
    days = max(0, min(days, 365))
    since = datetime.now(UTC) - timedelta(days=days) if days else None

    def _window(column: Any) -> list[Any]:
        return [column >= since] if since is not None else []

    # --- outcomes -----------------------------------------------------
    outcome_rows = db.execute(
        select(Message.outcome, func.count())
        .where(Message.bank_id == bank.id, Message.role == "assistant")
        .where(*_window(Message.created_at))
        .group_by(Message.outcome)
    ).all()
    counts = {outcome: n for outcome, n in outcome_rows if outcome}
    # Assistant turns written before migration 0007 carry no outcome. Reported
    # rather than dropped: a reader is entitled to know some turns aren't
    # represented in the percentages above them.
    unclassified = sum(n for outcome, n in outcome_rows if not outcome)

    substantive = sum(counts.get(o, 0) for o in agent_module.SUBSTANTIVE)
    resolved = sum(counts.get(o, 0) for o in agent_module.RESOLVED)
    answered = counts.get(agent_module.ANSWERED, 0)

    # --- conversations, languages, channels ---------------------------
    conversations = db.execute(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.bank_id == bank.id)
        .where(*_window(Conversation.created_at))
    ).scalar_one()

    languages = [
        {
            "language": lang or "unknown",
            "name": LANGUAGE_NAMES.get(lang or "", "Unknown"),
            "count": n,
        }
        for lang, n in db.execute(
            select(Conversation.language, func.count())
            .where(Conversation.bank_id == bank.id)
            .where(*_window(Conversation.created_at))
            .group_by(Conversation.language)
        ).all()
    ]
    languages.sort(key=lambda row: (-int(row["count"]), str(row["language"])))

    channels = [
        {"channel": channel, "count": n}
        for channel, n in db.execute(
            select(Conversation.channel, func.count())
            .where(Conversation.bank_id == bank.id)
            .where(*_window(Conversation.created_at))
            .group_by(Conversation.channel)
        ).all()
    ]
    channels.sort(key=lambda row: -int(row["count"]))

    # --- what customers actually asked --------------------------------
    # Grouped by content signature, the same way content gaps are, so the two
    # reports name the same topic the same way.
    #
    # Filtered on the recorded outcome, never on the guessed intent. A reply of
    # "Oli 0911234567" to the contact request classifies as an ordinary
    # question, so an intent filter ranked a customer's name and phone number
    # as a top topic — wrong as analytics, and personal data surfacing in the
    # one report most likely to be exported and shown around.
    question_rows = db.execute(
        select(Message.text)
        .where(
            Message.bank_id == bank.id,
            Message.role == "user",
            Message.outcome.in_(agent_module.SUBSTANTIVE),
        )
        .where(*_window(Message.created_at))
        .order_by(Message.created_at.desc())
        .limit(2000)
    ).scalars().all()

    topics: dict[str, dict[str, Any]] = {}
    for text in question_rows:
        # Scrubbed before the signature is computed, so a volunteered number
        # can reach neither the grouping key nor the example.
        question = redact_contact((text or "").strip())
        if not question:
            continue
        key = content_signature(question) or question.lower()
        topic = topics.setdefault(key, {"signature": key, "count": 0, "example": question})
        topic["count"] += 1
    top_topics = sorted(topics.values(), key=lambda t: (-int(t["count"]), str(t["signature"])))

    # --- the handoff queue, as work rather than history ---------------
    handoff_rows = db.execute(
        select(Handoff.status, Handoff.contact_phone)
        .where(Handoff.bank_id == bank.id)
        .where(*_window(Handoff.created_at))
    ).all()
    open_handoffs = [h for h in handoff_rows if h.status == "open"]
    reachable = sum(1 for h in open_handoffs if h.contact_phone)

    return {
        "window_days": days,
        "since": since.isoformat() if since else None,
        "conversations": conversations,
        "substantive_questions": substantive,
        "resolved_without_a_person": resolved,
        # Null, not zero, when nothing has been asked yet.
        "deflection_rate": round(resolved / substantive, 4) if substantive else None,
        "answered_from_own_content": answered,
        "own_content_rate": round(answered / substantive, 4) if substantive else None,
        "outcomes": [
            {"outcome": o, "count": counts.get(o, 0)}
            for o in (*agent_module.SUBSTANTIVE, agent_module.GREETING,
                      agent_module.CONTACT_CAPTURED)
            if counts.get(o, 0)
        ],
        "unclassified_turns": unclassified,
        "languages": languages,
        "channels": channels,
        "top_topics": top_topics[:MAX_TOP_TOPICS],
        "handoffs": {
            "open": len(open_handoffs),
            "closed": sum(1 for h in handoff_rows if h.status != "open"),
            # Of the people still waiting on a callback, how many can actually
            # be called. An open handoff nobody can reach is a dead letter.
            "open_reachable": reachable,
            "open_unreachable": len(open_handoffs) - reachable,
        },
    }


@app.post("/admin/api/{slug}/handoffs/{handoff_id}/close")
def close_handoff(
    handoff_id: str, bank: Bank = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, str]:
    handoff = db.get(Handoff, handoff_id)
    if handoff is None or handoff.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown handoff")
    handoff.status = "closed"
    _audit(db, bank, "handoff_closed", "handoff", handoff.id, None)
    db.commit()
    return {"status": "closed"}
