from __future__ import annotations

import hmac
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import telegram
from .agent import handle_message
from .config import get_settings
from .db import get_db, init_db
from .i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES
from .logging_config import configure_logging, log_event
from .models import AuditLog, Bank, Conversation, Document, Handoff, Message, new_token
from .ratelimit import SlidingWindowLimiter
from .retrieval import reindex_document

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


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    category: str = "general"
    language: str = "en"


class HealthOut(BaseModel):
    status: str
    llm: str


# ---------------------------------------------------------------- public


@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    settings = get_settings()
    mode = "gemini" if settings.gemini_api_key else "extractive-fallback"
    return HealthOut(status="ok", llm=mode)


@app.get("/banks/{slug}/public")
def bank_public(slug: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    bank = _get_bank(db, slug)
    return {
        "name": bank.name,
        "slug": bank.slug,
        "primary_color": bank.primary_color,
        "default_language": bank.default_language,
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
    )


@app.get("/widget")
def widget_page() -> FileResponse:
    return FileResponse(_STATIC / "widget.html", media_type="text/html")


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(_STATIC / "admin.html", media_type="text/html")


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
        }
        for h in rows
    ]


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
