from __future__ import annotations

import hmac
import json
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, sessionmaker

from . import (
    admin_auth,
    channels,
    classifier,
    departments,
    faq,
    handoff_webhook,
    i18n,
    ingest,
    livekit,
    llm,
    meta,
    passwords,
    permissions,
    presence,
    roles,
    sms,
    telegram,
    teller,
    verification,
    viber,
)
from . import agent as agent_module
from .agent import handle_message
from .classifier import redact_contact
from .config import get_settings
from .db import get_db, get_engine, init_db
from .i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES
from .i18n import t as translate
from .llm import active_backend, credentials_ready
from .logging_config import configure_logging, log_event
from .models import (
    AuditLog,
    Bank,
    Conversation,
    Document,
    Faq,
    Handoff,
    Message,
    Role,
    TellerSession,
    User,
    UserCredential,
    _utc,
    new_token,
)
from .ratelimit import SlidingWindowLimiter
from .retrieval import content_signature, reindex_document

logger = logging.getLogger(__name__)


def iso(value: datetime | None) -> str | None:
    """A timestamp a browser can read correctly, from either database.

    Postgres returns aware values from `DateTime(timezone=True)`; SQLite has
    no timezone type and returns naive ones, so `.isoformat()` produced
    "2026-08-10T19:12:33" with no offset. Per the ECMAScript spec a browser
    reads a date-TIME form without an offset as LOCAL time, so every one of
    these was wrong by the viewer's UTC offset — in Addis, three hours into
    the future, which is how a conversation that just happened rendered as a
    negative age. Production runs Postgres and was unaffected; every local
    and SQLite deployment was not, and relying on the database to make the
    wire format correct is a trap that only stays quiet by luck.
    """
    return None if value is None else _utc(value).isoformat()

_STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    app.state.ip_limiter = SlidingWindowLimiter(settings.chat_rate_per_ip)
    app.state.conversation_limiter = SlidingWindowLimiter(settings.chat_rate_per_conversation)
    # Counts FAILED admin auth attempts only — see require_admin.
    app.state.admin_auth_limiter = SlidingWindowLimiter(settings.admin_auth_failures_per_ip)
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
    request: Request,
    x_admin_token: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Bank:
    """Authenticate a tenant admin, and make a failed attempt visible.

    Two things were missing and both are the same problem: nothing recorded a
    rejected attempt, and nothing slowed one down. A credential-stuffing run
    against this endpoint left no trace at all — the token itself is 192 bits
    so guessing it is not the realistic threat, but *not knowing anyone tried*
    is, and a bank's security review asks about detection before strength.

    The limiter counts FAILURES ONLY, never successful calls. Throttling a
    legitimate operator working a busy handoff queue would be a denial of
    service dressed up as a security control, and it is exactly the kind of
    protection that gets switched off in month two.

    An unknown slug is deliberately answered with the same 401 as a wrong
    token, and counted the same way, so a probe cannot tell a typo from a
    wrong credential. This is defence in depth rather than a secret kept:
    /chat/{slug} still 404s, and a live tenant's slug is public anyway — it
    sits in the widget URL on the bank's own website. What it does protect is
    a tenant that has been created but not yet launched, and it keeps the
    failure accounting uniform, which is what makes the log usable.
    """
    client_ip = request.client.host if request.client else "unknown"
    limiter: SlidingWindowLimiter = request.app.state.admin_auth_limiter
    key = f"admin:{slug}:{client_ip}"

    def _reject(reason: str) -> HTTPException:
        # The attempted token is never logged. It may be a real credential
        # for another tenant — someone pasting the wrong one — and logs are
        # the easiest place for a secret to end up somewhere unaudited.
        allowed = limiter.allow(key)
        log_event(
            logger,
            "admin_auth_failed",
            bank=slug,
            client_ip=client_ip,
            reason=reason,
            token_present=bool(x_admin_token),
            rate_limited=not allowed,
        )
        if not allowed:
            return HTTPException(
                status_code=429, detail="Too many failed attempts, please slow down"
            )
        return HTTPException(status_code=401, detail="Invalid admin token")

    bank = db.execute(select(Bank).where(Bank.slug == slug)).scalar_one_or_none()
    if bank is None:
        raise _reject("unknown_bank")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, bank.admin_token):
        raise _reject("bad_token")
    return bank


TOKEN_ACTOR = "admin-token"
"""What the audit log records when the break-glass token acted.

Honest about being unattributable. The alternative — writing "admin", as every
row did before per-person logins — reads like a person and is not one, and an
audit trail that quietly invents an actor is worse than one that admits it has
no name for this.
"""


@dataclass(frozen=True)
class Principal:
    """Who is making this request.

    Either a signed-in person or the tenant's break-glass token, resolved to
    the one bank they are allowed to act on. Routes take this instead of a
    `Bank` so that every action already knows who to attribute.
    """

    bank: Bank
    user: User | None  # None when the shared token authenticated this call

    @property
    def audit_actor(self) -> str:
        return self.user.id if self.user is not None else TOKEN_ACTOR


def _audit(db: Session, bank: Bank, action: str, entity_type: str, entity_id: str,
           metadata: dict[str, Any] | None = None, *, actor: str) -> None:
    """Record an admin action. `actor` is required and has no default.

    Deliberately not defaulted to `admin-token`. A default would let a new
    route silently attribute a person's action to the shared token, and the
    whole point of this change is that the log stops guessing. Making it
    required means mypy refuses to compile a call site that forgot — the
    reviewer does not have to notice.
    """
    db.add(
        AuditLog(
            bank_id=bank.id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            log_metadata=metadata,
        )
    )


def require(permission: str) -> Callable[..., Principal]:
    """Guard a route with a permission. Session first, token as break-glass.

    A route names a capability, never a role. That is what lets a bank move
    `documents.write` off its operators without anyone editing this file, and
    what makes "who can repoint the handoff webhook" a query rather than a
    reading of the source.

    Three properties worth being explicit about:

    **A session is bound to one tenant.** A person signed in at bank A calling
    bank B's URL is refused even if they are an administrator at A. Without
    this check the whole per-tenant model would be decoration — so it is
    asserted directly, not left to follow from how the routes happen to be
    written.

    **Lacking a permission is 403, not 401.** They are signed in; the answer is
    "not you", not "who are you". Collapsing the two would make the admin panel
    bounce a legitimate operator to the login screen where a clear refusal
    belongs.

    **The token holds every permission**, and is checked only after the session
    path declines. It is break-glass: bootstrapping a tenant's first user,
    automation with no person involved, and recovery when the last
    administrator locks themselves out. It audits as `admin-token`.
    """

    def dependency(
        slug: str,
        request: Request,
        x_admin_token: str = Header(default=""),
        db: Session = Depends(get_db),
    ) -> Principal:
        user = admin_auth.resolve(db, request.cookies.get(admin_auth.COOKIE_NAME))
        if user is not None:
            bank = _get_bank(db, slug)
            if user.bank_id != bank.id:
                # A session for another tenant does not refuse the request
                # outright — it steps aside for an explicitly supplied token.
                #
                # The cookie is ambient: the browser attaches it to anything
                # under /admin without being asked. The token is deliberate,
                # typed in for this call. Letting the ambient credential veto
                # the deliberate one is how someone administering several
                # tenants ends up staring at a 403 on a bank whose token they
                # hold and just entered. Explicit beats ambient.
                #
                # Nothing is loosened: the token still has to be the right one
                # for this bank. All that changes is which credential is
                # consulted when they disagree about who is asking.
                if x_admin_token and hmac.compare_digest(
                    x_admin_token, bank.admin_token
                ):
                    return Principal(bank=bank, user=None)
                # Deliberately 403 and not 404. Hiding the tenant's existence
                # from someone already authenticated elsewhere buys nothing —
                # slugs are public, they sit in the widget URL on the bank's
                # own website — and a 404 here would send an operator hunting
                # for a typo instead of telling them the truth.
                log_event(
                    logger, "admin_cross_tenant_denied",
                    bank=slug, user_id=user.id, user_bank_id=user.bank_id,
                    permission=permission,
                )
                raise HTTPException(
                    status_code=403, detail="Not permitted for this bank"
                )
            if not roles.user_has(db, user, permission):
                log_event(
                    logger, "admin_permission_denied",
                    bank=slug, user_id=user.id, permission=permission,
                )
                raise HTTPException(status_code=403, detail="Not permitted")
            return Principal(bank=bank, user=user)
        return Principal(bank=require_admin(slug, request, x_admin_token, db), user=None)

    return dependency


# One `Depends` per permission, built at import rather than per request.
#
# Also why routes read `= NeedsDocumentsWrite` rather than
# `= Depends(require(...))`: a call inside a default argument is evaluated once
# at import time. That is harmless here and is the shape of a real bug
# elsewhere, so ruff flags it (B008), and silencing that fifteen times would be
# worse than naming the dependencies once.
#
# This block is the entire access-control policy of the admin API, in one
# screen. `tests/test_permissions.py` fails if it drifts from the registry or
# leaves an admin route unguarded.
NeedsAnalyticsRead = Depends(require(permissions.Perm.ANALYTICS_READ))
NeedsConversationsRead = Depends(require(permissions.Perm.CONVERSATIONS_READ))
NeedsHandoffsRead = Depends(require(permissions.Perm.HANDOFFS_READ))
NeedsHandoffsResolve = Depends(require(permissions.Perm.HANDOFFS_RESOLVE))
NeedsGapsRead = Depends(require(permissions.Perm.GAPS_READ))
NeedsDocumentsRead = Depends(require(permissions.Perm.DOCUMENTS_READ))
NeedsDocumentsWrite = Depends(require(permissions.Perm.DOCUMENTS_WRITE))
NeedsIntegrationsManage = Depends(require(permissions.Perm.INTEGRATIONS_MANAGE))
NeedsAuditRead = Depends(require(permissions.Perm.AUDIT_READ))
NeedsUsersManage = Depends(require(permissions.Perm.USERS_MANAGE))
NeedsSessionsRead = Depends(require(permissions.Perm.SESSIONS_READ))
NeedsTellerServe = Depends(require(permissions.Perm.TELLER_SERVE))


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
    # Whether a live teller can be reached RIGHT NOW.
    #
    # On every turn, not just at page load. The widget read this once from
    # /banks/{slug}/public when it booted and never again — so a customer who
    # opened the chat before anyone came on duty was frozen on "no teller"
    # for the whole conversation, and the offer never appeared however long
    # they stayed. Availability is a fact about this minute; the moment it
    # matters is the moment a reply is being decided, which is here.
    teller_available: bool = False
    # What this turn actually did — agent's outcome vocabulary. Exposed because
    # intent alone mislabels every turn that isn't answering a question: storing
    # a customer's phone number was displayed as "Product guidance", inherited
    # from the placeholder intent the contact-capture path returns.
    outcome: str | None = None


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


# Presence lives in `presence.py` so the assistant and the widget read the
# same answer — see that module for why. Re-exported under the old names
# because they are what the tests and the rest of this file already say, and
# renaming a thing at the same time as moving it makes the diff unreadable.
TELLER_PRESENCE_WINDOW = presence.TELLER_PRESENCE_WINDOW
_teller_available = presence.teller_available


@app.get("/banks/{slug}/public")
def bank_public(
    slug: str, response: Response, db: Session = Depends(get_db)
) -> dict[str, Any]:
    bank = _get_bank(db, slug)
    # See admin_ui_strings: a label table must never be more cacheable than
    # the page that reads it. This payload also carries `teller_available`,
    # which is a live operational switch — a bank turning live sessions on
    # and staying invisible to customers behind a cached "false" is worse
    # than a stale label.
    response.headers.update(_NO_STORE)
    return {
        # What to put on screen. The widget's header and the admin's rail both
        # read this, and both want what the bank is called rather than what it
        # is registered as.
        "name": bank.display_name,
        # The registered name, for anywhere precision beats familiarity.
        "legal_name": bank.name,
        "slug": bank.slug,
        "primary_color": bank.primary_color,
        "logo_url": bank.logo_url,
        "default_language": bank.default_language,
        "disclaimer": bank.disclaimer,
        "languages": [
            {"code": code, "name": LANGUAGE_NAMES[code]} for code in SUPPORTED_LANGUAGES
        ],
        # Whether to offer a live teller right now — enabled AND somebody
        # actually watching the queue. A boolean rather than a headcount: how
        # thinly a bank staffs its queue is its business, not the public
        # internet's, and the customer only needs to know whether to wait.
        "teller_available": _teller_available(db, bank),
        # Every interface label, in every language, in one payload. The widget
        # has a language picker, and fetching a new table on each switch would
        # put a network round trip between a customer and the language they
        # can actually read — on the connection this product is used on, that
        # is the moment they give up. A few kilobytes once is the better
        # trade.
        "ui": i18n.all_ui_strings(),
    }


def _deliver_handoffs(bank_id: str, handoff_ids: list[str]) -> None:
    """Post each handoff to the bank's contact-centre tool, after the reply.

    Opens its own session. The request's session is closed by the time a
    background task runs, and reusing it would either fail or — worse — work
    intermittently depending on how the pool happened to be behaving.

    Nothing here can raise into anything: FastAPI runs background tasks
    outside the request, so an exception is logged by the framework and the
    customer never learns of it. Failing loudly would achieve nothing except
    noise, and the handoff is safely in the console either way.
    """
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    db = factory()
    try:
        bank = db.get(Bank, bank_id)
        if bank is None:
            return
        for handoff_id in handoff_ids:
            handoff = db.get(Handoff, handoff_id)
            # Tenancy, even here. A background task with a stale id must never
            # be able to post one bank's customer to another bank's endpoint.
            if handoff is None or handoff.bank_id != bank.id:
                continue
            handoff_webhook.deliver(bank, handoff)
    finally:
        db.close()


@app.post("/chat/{slug}", response_model=ChatResponse)
def chat(
    slug: str,
    payload: ChatRequest,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
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

    # handle_message has committed by now, so the handoff exists whatever
    # happens next. Delivery runs after the response is sent: a bank's CRM
    # being slow or down must never add its timeout to a customer's reply, and
    # a customer reporting theft gets their acknowledgement either way.
    if result.handoff_ids and bank.handoff_webhook_url:
        background.add_task(_deliver_handoffs, bank.id, list(result.handoff_ids))

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
        outcome=result.outcome,
        teller_available=_teller_available(db, bank),
    )


# Both pages are single files with their CSS and JS inlined, so a cached
# copy pins the *entire* UI — after a deploy a returning visitor keeps
# seeing the old widget with no way to tell, which is exactly what happened
# after the capability-chip redesign shipped. There is no hashed-asset
# filename to bust here, so the HTML itself must not be cached. These are
# tiny documents served on a cold open; revalidating costs nothing next to
# demoing a stale UI to a prospect.
_NO_STORE = {"Cache-Control": "no-store, must-revalidate"}


@app.get("/embed.js")
def embed_script() -> FileResponse:
    """The loader a bank pastes onto its own site.

    Cached, unlike the pages: this is fetched by every visitor to the bank's
    website rather than by the handful of people who open the admin panel, and
    a no-store script would be a request on every page view of a bank's site
    for a file that changes a few times a year.
    """
    return FileResponse(
        _STATIC / "embed.js",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/vendor/livekit-client.umd.js")
def livekit_sdk() -> FileResponse:
    """The LiveKit browser SDK, served from our own origin.

    Vendored rather than loaded from a CDN, deliberately. This script runs on
    a BANK'S OWN PAGE — a third-party CDN there is a script tag their security
    review has to justify, a Content-Security-Policy entry they have to widen,
    and an outage nobody in this project can fix. The file is in the repo,
    pinned, auditable, and served from the same origin as everything else.

    Apache 2.0, licence alongside it in static/vendor. Already minified as
    shipped (~141 KB gzipped), so there is no build step — which matters in a
    repo that deliberately has none.

    Cached hard: it is immutable for a given release and every customer who
    opens a call fetches it.
    """
    return FileResponse(
        _STATIC / "vendor" / "livekit-client.umd.js",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=86400"},
    )


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
    started = conversation is None
    if conversation is None:
        conversation = Conversation(
            bank_id=bank.id, channel="telegram", external_user_id=external_id
        )
        db.add(conversation)
        db.flush()

    # The disclaimer leads the conversation, because Telegram has nowhere to
    # put it permanently.
    #
    # In the widget it is a banner pinned above every message, and the widget
    # only reaches someone already on a page the bank controls. A bot is the
    # opposite on both counts: it is publicly discoverable by username, anyone
    # can start a chat with it, and there is no persistent surface to hold a
    # notice. For a prospect-demo tenant — a bot wearing a bank's name that the
    # bank has not endorsed — an unlabelled first reply is the single most
    # consequential thing this product could get wrong, so it is sent before
    # the assistant says anything at all.
    #
    # Once per conversation, on the row being created. Repeating it on every
    # message would train people to scroll past it.
    if started and bank.disclaimer and bank.telegram_bot_token:
        telegram.send_message(bank.telegram_bot_token, chat_id, bank.disclaimer)

    # /start is Telegram's own "open the bot" command, not something a customer
    # typed to ask a question. Feeding it to the agent produces an answer to a
    # question nobody asked; it gets the greeting the widget opens with.
    # Split, because Telegram appends a deep-link payload: "/start ref123".
    if text.split(maxsplit=1)[0] == "/start":
        db.commit()
        if bank.telegram_bot_token:
            telegram.send_message(
                bank.telegram_bot_token,
                chat_id,
                translate(bank.default_language, "greeting", bank=bank.display_name),
            )
        return {"ok": True}

    result = handle_message(db, bank, conversation, text)
    if bank.telegram_bot_token:
        telegram.send_message(bank.telegram_bot_token, chat_id, result.reply)
    return {"ok": True}


# --------------------------------------------------------- channel plumbing


def _connected_channels(bank: Bank) -> dict[str, bool]:
    """Which channels this tenant holds credentials for.

    One definition, because the Settings screen and the analytics breakdown
    both ask, and answering differently in two places is how a channel gets
    reported live on one page and available on the other.

    A channel counts as connected only when it has everything it needs to
    SEND. WhatsApp needs a phone number id as well as a token, and Meta's app
    secret alone lets a delivery in without letting a reply out — which is not
    "live" to a customer waiting for an answer.
    """
    return {
        "telegram_connected": bool(bank.telegram_bot_token),
        "viber_connected": bool(bank.viber_auth_token),
        "whatsapp_connected": bool(
            bank.whatsapp_access_token and bank.whatsapp_phone_number_id
        ),
        "messenger_connected": bool(bank.messenger_page_token),
        "instagram_connected": bool(bank.instagram_access_token),
        "sms_connected": bool(bank.sms_send_url),
    }


def _channel_reply(
    db: Session,
    bank: Bank,
    channel: str,
    external_id: str,
    text: str,
    send: Callable[[str], object],
) -> None:
    """One inbound message on any non-web channel, answered.

    Every messaging channel repeats the same four steps — find or open this
    person's conversation, lead with the disclaimer if it is new, run the
    agent, send the reply — and only the transport differs. With five channels
    that is four chances to drop the disclaimer on the newest adapter and
    nowhere for a test to notice.

    `send` takes the finished text and does whatever the channel needs.

    The disclaimer is tied to the conversation row being NEW, not to any
    channel's "chat opened" event, because those events are unreliable across
    channels: Viber only fires one on a fresh chat, WhatsApp has none at all,
    and a returning customer would silently get an unlabelled bot.
    """
    conversation = db.execute(
        select(Conversation).where(
            Conversation.bank_id == bank.id,
            Conversation.channel == channel,
            Conversation.external_user_id == external_id,
        )
    ).scalar_one_or_none()

    if conversation is None:
        conversation = Conversation(
            bank_id=bank.id, channel=channel, external_user_id=external_id
        )
        db.add(conversation)
        db.flush()
        if bank.disclaimer:
            send(bank.disclaimer)

    result = handle_message(db, bank, conversation, text)
    send(result.reply)


# ------------------------------------------------------------------- viber


@app.post("/webhooks/viber/{slug}")
async def viber_webhook(
    slug: str, request: Request, db: Session = Depends(get_db)
) -> dict[str, bool]:
    bank = _get_bank(db, slug)

    # The raw body, before any parsing: the signature covers the exact bytes
    # Viber sent, so re-serialising the parsed JSON would produce a different
    # string and fail every check.
    raw = await request.body()
    if not viber.valid_signature(
        bank.viber_auth_token or "",
        raw,
        request.headers.get("X-Viber-Content-Signature", ""),
    ):
        raise HTTPException(status_code=403, detail="Bad webhook signature")

    try:
        event = json.loads(raw or b"{}")
    except ValueError:
        # Signature-valid but unparseable should not be a 500 — a 500 makes
        # Viber retry the same broken body indefinitely.
        logger.warning("viber sent a signed body that is not JSON")
        return {"ok": True}
    kind = event.get("event")

    # Viber's own validation ping, sent the moment set_webhook is called and
    # before any customer exists. It must return 200 or registration fails.
    if kind in {"webhook", "delivered", "seen", "failed", "unsubscribed"}:
        return {"ok": True}

    # `conversation_started` is Viber's analogue of Telegram's /start: the
    # customer opened the chat and has typed nothing. `user` carries the
    # identity here, where a `message` event uses `sender`.
    if kind == "conversation_started":
        person = event.get("user") or {}
        receiver = person.get("id")
        if receiver and bank.viber_auth_token:
            # Disclaimer first, for the reason spelled out on the Telegram
            # route: a bot is publicly discoverable and has no pinned banner.
            if bank.disclaimer:
                viber.send_message(
                    bank.viber_auth_token, receiver, bank.disclaimer, bank.display_name
                )
            viber.send_message(
                bank.viber_auth_token,
                receiver,
                translate(bank.default_language, "greeting", bank=bank.display_name),
                bank.display_name,
            )
        return {"ok": True}

    if kind != "message":
        return {"ok": True}

    message = event.get("message") or {}
    text = message.get("text")
    sender = event.get("sender") or {}
    external_id = sender.get("id")
    # Stickers, images and location shares all arrive as `message` events with
    # no text. There is nothing for the agent to read, and answering anyway
    # would mean replying to a question nobody asked.
    if not text or not external_id:
        return {"ok": True}

    external_id = str(external_id)
    token = bank.viber_auth_token or ""
    _channel_reply(
        db, bank, "viber", external_id, text,
        lambda body: viber.send_message(token, external_id, body, bank.display_name),
    )
    return {"ok": True}


class ViberConnectIn(BaseModel):
    auth_token: str = Field(min_length=10)


@app.post("/admin/api/{slug}/viber/connect")
def viber_connect(
    slug: str, payload: ViberConnectIn,
    principal: Principal = NeedsIntegrationsManage, db: Session = Depends(get_db),
) -> dict[str, Any]:
    bank = principal.bank
    webhook_url = f"{get_settings().app_base_url}/webhooks/viber/{bank.slug}"

    # Committed BEFORE the call, and rolled forward if it fails.
    #
    # Viber validates a registration by immediately POSTing a `webhook` event
    # to the URL, and that arrives as a separate HTTP request on its own
    # database connection. An uncommitted flush is invisible to it, so the
    # ping would read a null token, fail the signature check with a 403, and
    # Viber would reject the registration — a connect that can never succeed.
    #
    # The cost is a window where the column holds a token whose webhook is not
    # registered. That is harmless: the column is only ever read to verify an
    # inbound signature, so an unregistered token accepts nothing and sends
    # nothing. The reverse order is what breaks.
    previous = bank.viber_auth_token
    bank.viber_auth_token = payload.auth_token
    db.commit()
    try:
        response = viber.set_webhook(payload.auth_token, webhook_url)
    except Exception as exc:  # noqa: BLE001
        # Put back whatever was there, so a failed paste does not silently
        # disconnect a channel that was working a moment ago.
        bank.viber_auth_token = previous
        db.commit()
        raise HTTPException(status_code=400, detail=f"Viber rejected the token: {exc}") from exc

    _audit(db, bank, "viber_connected", "bank", bank.id, {"webhook_url": webhook_url},
           actor=principal.audit_actor)
    db.commit()
    return {"webhook_url": webhook_url, "viber_response": response}


# -------------------------------------------------------------------- meta


@app.get("/webhooks/meta/{slug}")
def meta_verify(
    slug: str, request: Request, db: Session = Depends(get_db)
) -> Response:
    """Meta's subscription handshake.

    Answers with the challenge as **bare text**, not JSON: Meta compares the
    body byte-for-byte, and a quoted JSON string does not match. Getting this
    wrong means the callback can never be registered, with no partial state
    to debug from.
    """
    bank = _get_bank(db, slug)
    params = request.query_params
    challenge = meta.verify_handshake(
        mode=params.get("hub.mode", ""),
        token=params.get("hub.verify_token", ""),
        challenge=params.get("hub.challenge", ""),
        expected_token=bank.meta_verify_token or "",
    )
    if challenge is None:
        raise HTTPException(status_code=403, detail="Bad verify token")
    return PlainTextResponse(challenge)


@app.post("/webhooks/meta/{slug}")
async def meta_webhook(
    slug: str, request: Request, db: Session = Depends(get_db)
) -> dict[str, bool]:
    """One route for WhatsApp, Messenger and Instagram.

    Not a shortcut — it is how Meta works. Three products of one app deliver
    to one callback URL, signed with one app secret, and the `object` field
    says which product a delivery belongs to.
    """
    bank = _get_bank(db, slug)
    raw = await request.body()
    if not meta.valid_signature(
        bank.meta_app_secret or "",
        raw,
        request.headers.get("X-Hub-Signature-256", ""),
    ):
        raise HTTPException(status_code=403, detail="Bad webhook signature")

    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        logger.warning("meta sent a signed body that is not JSON")
        return {"ok": True}

    channel, messages = meta.inbound(payload)
    if channel is None:
        return {"ok": True}

    # A channel with no send credential is not connected, whatever the app is
    # subscribed to. Answering would run the agent and then drop the reply on
    # the floor — the customer waits, and nothing says why.
    sender = _meta_sender(bank, channel)
    if sender is None:
        logger.warning("meta delivery for unconfigured channel %s", channel)
        return {"ok": True}

    # Meta batches: one delivery can carry several messages, and may repeat
    # them on retry. Each is answered in its own conversation lookup.
    for external_id, text in messages:
        _channel_reply(db, bank, channel, external_id, text, _bind(sender, external_id))
    return {"ok": True}


def _bind(send: Callable[[str, str], object], to: str) -> Callable[[str], object]:
    """Fix the recipient, leaving a one-argument send for `_channel_reply`.

    A named function rather than a lambda with a default argument, because
    Meta batches several messages into one delivery: a lambda closing over the
    loop variable would send every reply in the batch to whoever happened to
    be last.
    """
    return lambda body: send(to, body)


def _meta_sender(bank: Bank, channel: str) -> Callable[[str, str], object] | None:
    """The send call for a Meta channel, or None if it is not configured."""
    if channel == meta.WHATSAPP:
        if not (bank.whatsapp_access_token and bank.whatsapp_phone_number_id):
            return None
        token, number = bank.whatsapp_access_token, bank.whatsapp_phone_number_id
        return lambda to, text: meta.send_whatsapp(token, number, to, text)
    if channel == meta.MESSENGER:
        if not bank.messenger_page_token:
            return None
        page = bank.messenger_page_token
        return lambda to, text: meta.send_messaging(page, to, text, channel=channel)
    if channel == meta.INSTAGRAM:
        if not bank.instagram_access_token:
            return None
        ig = bank.instagram_access_token
        return lambda to, text: meta.send_messaging(ig, to, text, channel=channel)
    return None


class MetaConnectIn(BaseModel):
    """Credentials for a Meta app. Every send-side field is optional so a bank
    can switch on whichever products its review actually cleared."""

    app_secret: str = Field(min_length=10)
    whatsapp_phone_number_id: str | None = None
    whatsapp_access_token: str | None = None
    messenger_page_token: str | None = None
    instagram_access_token: str | None = None


@app.post("/admin/api/{slug}/meta/connect")
def meta_connect(
    slug: str, payload: MetaConnectIn,
    principal: Principal = NeedsIntegrationsManage, db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Store Meta credentials and mint the verify token.

    No outbound call: unlike Telegram and Viber, Meta's callback is registered
    from *its* dashboard, not by us. So this hands back the URL and the token
    to paste there — which is also why the verify token is generated here
    rather than typed, so it cannot be a guessable one somebody chose.
    """
    bank = principal.bank
    bank.meta_app_secret = payload.app_secret
    if not bank.meta_verify_token:
        bank.meta_verify_token = new_token()
    for field in (
        "whatsapp_phone_number_id", "whatsapp_access_token",
        "messenger_page_token", "instagram_access_token",
    ):
        value = getattr(payload, field)
        if value:
            setattr(bank, field, value)

    callback_url = f"{get_settings().app_base_url}/webhooks/meta/{bank.slug}"
    _audit(db, bank, "meta_connected", "bank", bank.id, {"callback_url": callback_url},
           actor=principal.audit_actor)
    db.commit()
    return {"callback_url": callback_url, "verify_token": bank.meta_verify_token}


# --------------------------------------------------------------------- sms


@app.post("/webhooks/sms/{slug}")
async def sms_webhook(
    slug: str, request: Request, db: Session = Depends(get_db)
) -> dict[str, bool]:
    """An inbound SMS from the bank's aggregator.

    Authenticated with a shared secret rather than a signature: aggregators
    do not sign bodies the way Meta and Viber do, and inventing a scheme they
    will not implement would make the channel unusable. Compared with
    `compare_digest`, and fails closed when unset.
    """
    bank = _get_bank(db, slug)
    secret = bank.sms_inbound_secret or ""
    presented = request.headers.get("X-SMS-Secret", "")
    if not secret or not presented or not hmac.compare_digest(secret, presented):
        raise HTTPException(status_code=403, detail="Bad SMS secret")

    # Aggregators split roughly evenly between form posts and JSON.
    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        try:
            fields = json.loads(await request.body() or b"{}")
        except ValueError:
            return {"ok": True}
    else:
        fields = dict(await request.form())

    number, text = sms.parse_inbound(fields)
    if not number or not text:
        return {"ok": True}

    send_url = bank.sms_send_url or ""
    auth = bank.sms_auth_header or ""
    sender_id = bank.sms_sender_id or bank.display_name
    _channel_reply(
        db, bank, "sms", number, text,
        lambda body: sms.send_message(
            send_url=send_url, auth_header=auth, to=number,
            text=body, sender_id=sender_id,
        ),
    )
    return {"ok": True}


class SmsConnectIn(BaseModel):
    send_url: str = Field(min_length=8)
    auth_header: str | None = None
    sender_id: str | None = None


@app.post("/admin/api/{slug}/sms/connect")
def sms_connect(
    slug: str, payload: SmsConnectIn,
    principal: Principal = NeedsIntegrationsManage, db: Session = Depends(get_db),
) -> dict[str, Any]:
    bank = principal.bank
    bank.sms_send_url = payload.send_url
    bank.sms_auth_header = payload.auth_header
    bank.sms_sender_id = payload.sender_id
    if not bank.sms_inbound_secret:
        bank.sms_inbound_secret = new_token()
    callback_url = f"{get_settings().app_base_url}/webhooks/sms/{bank.slug}"
    _audit(db, bank, "sms_connected", "bank", bank.id, {"callback_url": callback_url},
           actor=principal.audit_actor)
    db.commit()
    return {"callback_url": callback_url, "inbound_secret": bank.sms_inbound_secret}


class TelegramConnectIn(BaseModel):
    bot_token: str = Field(min_length=10)


@app.post("/admin/api/{slug}/telegram/connect")
def telegram_connect(
    slug: str, payload: TelegramConnectIn,
    principal: Principal = NeedsIntegrationsManage, db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Store the bot token and register our webhook with Telegram.

    `telegram.set_webhook()` calls `raise_for_status()`, so a rejection
    (wrong token, malformed webhook URL) raised an uncaught
    `httpx.HTTPStatusError` here — FastAPI's default handler turned that
    into a bare 500 with no message, which is what an operator pasting a
    typo'd token actually saw in production. `viber_connect`, two functions
    above this one, already gets this right: catch, roll back the token so
    a failed paste doesn't silently disconnect a channel that was working,
    and surface Telegram's own `description` field — "Bad Request: wrong
    bot token" tells an operator what to fix; a 500 does not.
    """
    import httpx

    bank = principal.bank
    previous_token = bank.telegram_bot_token
    previous_secret = bank.telegram_webhook_secret
    bank.telegram_bot_token = payload.bot_token
    bank.telegram_webhook_secret = new_token()
    webhook_url = f"{get_settings().app_base_url}/webhooks/telegram/{bank.slug}"
    try:
        response = telegram.set_webhook(
            payload.bot_token, webhook_url, bank.telegram_webhook_secret
        )
    except httpx.HTTPStatusError as exc:
        bank.telegram_bot_token = previous_token
        bank.telegram_webhook_secret = previous_secret
        db.commit()
        try:
            reason = exc.response.json().get("description", str(exc))
        except Exception:  # noqa: BLE001 — the JSON parse itself, not the request
            reason = str(exc)
        raise HTTPException(
            status_code=400, detail=f"Telegram rejected the token: {reason}"
        ) from exc
    except httpx.HTTPError as exc:
        bank.telegram_bot_token = previous_token
        bank.telegram_webhook_secret = previous_secret
        db.commit()
        raise HTTPException(status_code=502, detail=f"Could not reach Telegram: {exc}") from exc

    _audit(db, bank, "telegram_connected", "bank", bank.id, {"webhook_url": webhook_url},
           actor=principal.audit_actor)
    db.commit()
    return {"webhook_url": webhook_url, "telegram_response": response}


# ---------------------------------------------------------------- admin identity
#
# Nothing below is wired into the existing admin routes yet. They all still
# authenticate with banks.admin_token, deliberately: switching them over is a
# separate change, so a mistake here cannot lock a bank out of its dashboard.


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class CreateUserIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=passwords.MIN_LENGTH, max_length=1024)
    display_name: str | None = Field(default=None, max_length=120)
    role: str = Field(default="operator")


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=passwords.MIN_LENGTH, max_length=1024)


def _identity(db: Session, user: User) -> dict[str, Any]:
    """What the admin panel is told about the person it just signed in.

    Includes the permission list, so the UI can hide what this person cannot
    do instead of offering buttons that answer 403. That is a courtesy, never
    a control — `require()` is the control and it re-checks on every request.
    A tampered response can hide a button; it cannot grant anything.
    """
    role = db.get(Role, user.role_id)
    return {
        "email": user.email,
        "display_name": user.display_name,
        "role": role.name if role is not None else None,
        "permissions": sorted(roles.permissions_for_user(db, user)),
        "bank_id": user.bank_id,
        # Every admin label in every language, sent with the identity the
        # panel already fetches on boot. Same reasoning as the widget: a
        # teller switching language mid-shift should not wait on a request,
        # and fifty-eight short labels across five languages is nothing.
        "ui": i18n.all_admin_strings(),
    }


def _set_session_cookie(response: Response, token: str) -> None:
    """httpOnly, Secure, SameSite=Strict, scoped to /admin.

    httpOnly because the token this replaces lives in localStorage, where any
    script on the page can read it. Strict rather than Lax because an admin
    panel has no cross-site navigation worth preserving, and Strict is what
    makes cross-site request forgery a non-issue without a separate token.
    Path=/admin so the cookie is never attached to /chat, which is public and
    cross-origin.
    """
    response.set_cookie(
        admin_auth.COOKIE_NAME,
        token,
        max_age=int(admin_auth.SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=get_settings().admin_cookie_secure,
        samesite="strict",
        path="/admin",
    )


def current_user(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    """The signed-in person, or None. Does not reject — see require_user."""
    return admin_auth.resolve(db, request.cookies.get(admin_auth.COOKIE_NAME))


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


@app.post("/admin/api/{slug}/login")
def login(
    slug: str,
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Sign in. One failure message for every cause.

    Unknown email, wrong password, disabled account and unknown tenant all
    return the same 401. Distinguishing them turns this into an oracle for
    "does this person have an account at this bank", which is worth more to an
    attacker than it is to a user who mistyped.

    Rate limited BEFORE the hash is computed. Argon2 is deliberately expensive
    — that is the point of it — which makes an unauthenticated endpoint that
    hashes on demand a denial-of-service amplifier unless something upstream
    caps the rate.
    """
    client_ip = request.client.host if request.client else "unknown"
    limiter: SlidingWindowLimiter = request.app.state.admin_auth_limiter
    key = f"login:{slug}:{client_ip}"

    def _fail(reason: str) -> HTTPException:
        allowed = limiter.allow(key)
        log_event(
            logger, "admin_login_failed",
            bank=slug, client_ip=client_ip, reason=reason, rate_limited=not allowed,
        )
        if not allowed:
            return HTTPException(
                status_code=429, detail="Too many failed attempts, please slow down"
            )
        return HTTPException(status_code=401, detail="Invalid email or password")

    bank = db.execute(select(Bank).where(Bank.slug == slug)).scalar_one_or_none()
    if bank is None:
        # Still spend the hash. Returning early here would make an unknown
        # tenant measurably faster than a wrong password.
        passwords.verify_password(None, payload.password)
        raise _fail("unknown_bank")

    email = payload.email.strip().lower()
    user = db.execute(
        select(User).where(User.bank_id == bank.id, User.email == email)
    ).scalar_one_or_none()
    credential = (
        db.execute(
            select(UserCredential).where(
                UserCredential.user_id == user.id, UserCredential.kind == "password"
            )
        ).scalar_one_or_none()
        if user is not None
        else None
    )

    # verify_password burns the same work when the hash is None, so an unknown
    # email costs what a wrong password costs.
    if not passwords.verify_password(
        credential.secret_hash if credential else None, payload.password
    ):
        raise _fail("bad_credentials" if user is not None else "unknown_user")
    if user is None or not user.is_active:
        raise _fail("disabled")

    # Upgrade the stored hash if the cost parameters have been raised since it
    # was written. A successful login is the only moment the plaintext exists
    # to do it, so without this a parameter increase would protect new
    # accounts and leave every existing one at the old strength forever.
    if credential is not None and passwords.needs_rehash(credential.secret_hash):
        credential.secret_hash = passwords.hash_password(payload.password)

    token, _session = admin_auth.issue(
        db, user, ip=client_ip, user_agent=request.headers.get("user-agent")
    )
    user.last_login_at = datetime.now(UTC)
    _audit(db, bank, "admin_login", "user", user.id, {"email": user.email},
           actor=user.id)
    db.commit()

    _set_session_cookie(response, token)
    log_event(logger, "admin_login", bank=slug, user=user.email, client_ip=client_ip)
    return _identity(db, user)


@app.post("/admin/api/{slug}/logout")
def logout(
    request: Request, response: Response, db: Session = Depends(get_db)
) -> dict[str, bool]:
    token = request.cookies.get(admin_auth.COOKIE_NAME)
    if token:
        # Signing out takes you off the air. Leaving presence set would keep
        # the customer's Connect button lit for up to the staleness window
        # after the person behind it went home — the exact failure the window
        # exists to bound, arriving by the one route where we know for certain
        # they have left.
        signer = admin_auth.resolve(db, token)
        if signer is not None:
            presence.set_duty(signer, on_duty=False)
        admin_auth.revoke(db, token)
        db.commit()
    response.delete_cookie(admin_auth.COOKIE_NAME, path="/admin")
    return {"signed_out": True}


@app.get("/admin/strings")
def admin_ui_strings(response: Response) -> dict[str, dict[str, str]]:
    """The admin panel's labels, in every language it serves.

    Unauthenticated on purpose. These are interface strings — "Live queue",
    "End session" — and contain nothing about a tenant, a customer or a
    person. Requiring a session for them would be security theatre with a real
    cost: they were originally hung off the signed-in identity, and the
    break-glass token path has no user, so it rendered raw key names in the
    sidebar. A label table that only works when you are already signed in is a
    label table that fails on the one screen most likely to be reached in a
    hurry.
    """
    # no-store, and this is not belt-and-braces.
    #
    # /admin is already no-store, so the PAGE is always fresh. This response
    # had no cache headers at all, which lets a browser hold it under its own
    # heuristic — and a fresh page against a stale table is a specific,
    # confusing failure rather than a general one: every key that existed in
    # the cached copy renders translated and every key added since renders as
    # nothing useful. It looks exactly like "the sidebar is translated and the
    # dashboard is not", because the sidebar's keys are the older ones.
    #
    # A label table must never be more cacheable than the page that reads it.
    response.headers.update(_NO_STORE)
    return i18n.all_admin_strings()


@app.get("/admin/api/{slug}/me")
def me(
    user: User = Depends(require_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return _identity(db, user)


@app.post("/admin/api/{slug}/users", status_code=201)
def create_user(
    slug: str,
    payload: CreateUserIn,
    principal: Principal = NeedsUsersManage,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a colleague. Needs `users.manage`, or the break-glass token.

    The token path is the bootstrap: a tenant with no users yet has nobody who
    could authorise creating the first one, and that circle is the reason the
    shared token survives rather than being deleted.

    Setting a password directly here is acceptable *for bootstrap* and is not
    the intended way to onboard a team — that is an emailed invitation, which
    lands with the email service. Until then this is the only path, and it has
    the weakness the scope document names: the initial secret passes through
    whoever runs this call.

    The role is resolved by name against this bank's own roles, so a bank that
    has defined one of its own can assign it here without a code change. An
    unknown name is refused rather than defaulted — quietly creating someone as
    an `operator` because "supervisor" was misspelt would be a surprise in the
    direction of granting access nobody asked for.
    """
    bank = principal.bank
    role = roles.role_by_name(db, bank.id, payload.role)
    if role is None:
        available = sorted(
            r.name
            for r in db.execute(select(Role).where(Role.bank_id == bank.id)).scalars()
        )
        raise HTTPException(
            status_code=422, detail=f"Unknown role. This bank has: {available}"
        )

    email = payload.email.strip().lower()
    existing = db.execute(
        select(User).where(User.bank_id == bank.id, User.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A user with that email exists")

    user = User(
        bank_id=bank.id, email=email,
        display_name=payload.display_name, role_id=role.id,
    )
    db.add(user)
    db.flush()
    db.add(
        UserCredential(
            user_id=user.id, kind="password",
            secret_hash=passwords.hash_password(payload.password),
        )
    )
    # The password is never audited, logged or echoed back.
    _audit(db, bank, "user_created", "user", user.id,
           {"email": email, "role": role.name}, actor=principal.audit_actor)
    db.commit()
    return {"id": user.id, "email": user.email, "role": role.name}


@app.get("/admin/api/{slug}/users")
def list_users(
    principal: Principal = NeedsUsersManage, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """Everyone with access to this tenant, including the disabled.

    Disabled people are listed rather than hidden. "Who can get in here" is the
    question this screen exists to answer, and an answer that silently omits
    accounts is the wrong answer — an access review needs to see that someone
    was removed, not find no trace of them.
    """
    bank = principal.bank
    rows = db.execute(
        select(User, Role)
        .join(Role, Role.id == User.role_id)
        .where(User.bank_id == bank.id)
        .order_by(User.email)
    ).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "role": r.name,
            "is_active": u.is_active,
            "last_login_at": iso(u.last_login_at),
            "created_at": iso(u.created_at),
            # So the UI can disable its own row's button rather than offering an
            # action that is always refused.
            "is_you": principal.user is not None and principal.user.id == u.id,
        }
        for u, r in rows
    ]


@app.get("/admin/api/{slug}/roles")
def list_roles(
    principal: Principal = NeedsUsersManage, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """This bank's roles and exactly what each one grants.

    Served as data rather than described in a help page, because this is the
    table an access review asks for: "who can do what here". It is generated
    from the same rows `require()` checks, so it cannot describe a policy the
    system is not actually enforcing.
    """
    bank = principal.bank
    rows = db.execute(
        select(Role).where(Role.bank_id == bank.id).order_by(Role.name)
    ).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "is_builtin": r.is_builtin,
            "permissions": sorted(roles.permissions_for_role(db, r.id)),
        }
        for r in rows
    ]


class SetUserActiveIn(BaseModel):
    is_active: bool


@app.post("/admin/api/{slug}/users/{user_id}/active")
def set_user_active(
    user_id: str,
    payload: SetUserActiveIn,
    principal: Principal = NeedsUsersManage,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Disable or restore a colleague's access.

    Disabling revokes every session they hold, so it takes effect on their next
    request rather than whenever their current one happens to expire. Removing
    someone is the entire reason this feature exists; doing it with a delay
    would be theatre.

    You cannot disable yourself. Not a security control — the break-glass token
    could undo it — but the realistic version of this mistake is the only
    administrator locking themselves out mid-task, and refusing costs nothing.
    """
    bank = principal.bank
    target = db.get(User, user_id)
    if target is None or target.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown user")
    if (
        not payload.is_active
        and principal.user is not None
        and principal.user.id == target.id
    ):
        raise HTTPException(status_code=409, detail="You cannot disable yourself")

    revoked = 0
    if payload.is_active:
        target.disabled_at = None
    else:
        target.disabled_at = datetime.now(UTC)
        revoked = admin_auth.revoke_all_for_user(db, target.id)

    _audit(
        db, bank,
        "user_enabled" if payload.is_active else "user_disabled",
        "user", target.id,
        {"email": target.email, "sessions_revoked": revoked},
        actor=principal.audit_actor,
    )
    db.commit()
    return {"id": target.id, "is_active": target.is_active, "sessions_revoked": revoked}


@app.post("/admin/api/{slug}/me/password")
def change_own_password(
    slug: str,
    payload: ChangePasswordIn,
    request: Request,
    response: Response,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Change your own password, proving you know the current one.

    Every other session is revoked and this browser is issued a fresh one. A
    password change that left old sessions alive would leave whoever knew the
    old password still signed in — the opposite of what changing it is for,
    and the exact case where someone changes it *because* they think they were
    compromised.
    """
    credential = db.execute(
        select(UserCredential).where(
            UserCredential.user_id == user.id, UserCredential.kind == "password"
        )
    ).scalar_one_or_none()
    if not passwords.verify_password(
        credential.secret_hash if credential else None, payload.current_password
    ):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    assert credential is not None  # verify_password(None, ...) is always False

    credential.secret_hash = passwords.hash_password(payload.new_password)
    admin_auth.revoke_all_for_user(db, user.id)
    token, _ = admin_auth.issue(
        db, user,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    bank = db.get(Bank, user.bank_id)
    if bank is not None:
        _audit(db, bank, "password_changed", "user", user.id, {"email": user.email},
               actor=user.id)
    db.commit()
    _set_session_cookie(response, token)
    return {"changed": True}


class HandoffWebhookIn(BaseModel):
    # None disconnects. An empty string would be indistinguishable from a
    # typo, so turning it off has to be explicit.
    url: str | None = Field(default=None, max_length=500)


@app.post("/admin/api/{slug}/handoff-webhook")
def set_handoff_webhook(
    slug: str, payload: HandoffWebhookIn,
    principal: Principal = NeedsIntegrationsManage, db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Point handoffs at the bank's own contact-centre tool.

    The secret is generated here and returned exactly once. It cannot be read
    back afterwards — an admin token that leaks would otherwise hand over the
    means to forge handoffs into the bank's ticketing system, and a value the
    API will re-display is a value that ends up in a screenshot.

    Only https is accepted. The payload carries a customer's question and
    phone number, and posting that over plain http would put it on the wire in
    clear text on the way to a third party.
    """
    bank = principal.bank
    if payload.url is None:
        bank.handoff_webhook_url = None
        bank.handoff_webhook_secret = None
        _audit(db, bank, "handoff_webhook_disconnected", "bank", bank.id, {},
               actor=principal.audit_actor)
        db.commit()
        return {"connected": False}

    if not payload.url.startswith("https://"):
        raise HTTPException(status_code=422, detail="Webhook URL must be https")

    bank.handoff_webhook_url = payload.url
    secret = new_token()
    bank.handoff_webhook_secret = secret
    # The URL is audited; the secret never is. An audit log is read by more
    # people than the response to this call ever will be.
    _audit(db, bank, "handoff_webhook_connected", "bank", bank.id, {"url": payload.url},
           actor=principal.audit_actor)
    db.commit()
    return {
        "connected": True,
        "url": payload.url,
        "secret": secret,
        "signature_header": handoff_webhook.SIGNATURE_HEADER,
        "note": (
            "Store this secret now — it is not retrievable. Verify each POST by "
            "computing HMAC-SHA256 of the raw body with it and comparing "
            "against the signature header, using a constant-time comparison."
        ),
    }


# ---------------------------------------------------------------- admin: documents


@app.get("/admin/api/{slug}/documents")
def list_documents(
    principal: Principal = NeedsDocumentsRead, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    bank = principal.bank
    docs = db.execute(
        select(Document).where(Document.bank_id == bank.id).order_by(Document.updated_at.desc())
    ).scalars().all()
    return [
        {
            "id": d.id, "title": d.title, "category": d.category,
            "language": d.language, "updated_at": iso(d.updated_at),
            "content": d.content,
        }
        for d in docs
    ]


@app.post("/admin/api/{slug}/documents", status_code=201)
def create_document(
    payload: DocumentIn, principal: Principal = NeedsDocumentsWrite, db: Session = Depends(get_db)
) -> dict[str, Any]:
    bank = principal.bank
    doc = Document(
        bank_id=bank.id, title=payload.title, content=payload.content,
        category=payload.category, language=payload.language,
    )
    db.add(doc)
    db.flush()
    n_chunks = reindex_document(db, doc)
    _audit(db, bank, "document_created", "document", doc.id, {"chunks": n_chunks},
           actor=principal.audit_actor)
    db.commit()
    return {"id": doc.id, "chunks": n_chunks}


@app.post("/admin/api/{slug}/documents/bulk", status_code=201)
def bulk_create_documents(
    payload: DocumentBulkIn,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # All-or-nothing: reject the whole batch on any bad language code rather than
    # importing a partial knowledge base and leaving the admin to spot which rows
    # silently failed. This is the onboarding path for a bank's real KB, where a
    # dozens-of-documents batch getting half-imported is worse than getting none.
    bank = principal.bank
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
        actor=principal.audit_actor,
    )
    db.commit()
    return {"created": len(created), "ids": [d.id for d in created]}


@app.put("/admin/api/{slug}/documents/{document_id}")
def update_document(
    document_id: str, payload: DocumentIn,
    principal: Principal = NeedsDocumentsWrite, db: Session = Depends(get_db),
) -> dict[str, Any]:
    bank = principal.bank
    doc = db.get(Document, document_id)
    if doc is None or doc.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown document")
    doc.title, doc.content = payload.title, payload.content
    doc.category, doc.language = payload.category, payload.language
    n_chunks = reindex_document(db, doc)
    _audit(db, bank, "document_updated", "document", doc.id, {"chunks": n_chunks},
           actor=principal.audit_actor)
    db.commit()
    return {"id": doc.id, "chunks": n_chunks}


@app.delete("/admin/api/{slug}/documents/{document_id}", status_code=204)
def delete_document(
    document_id: str, principal: Principal = NeedsDocumentsWrite, db: Session = Depends(get_db)
) -> None:
    bank = principal.bank
    doc = db.get(Document, document_id)
    if doc is None or doc.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown document")
    _audit(db, bank, "document_deleted", "document", doc.id, {"title": doc.title},
           actor=principal.audit_actor)
    db.delete(doc)
    db.commit()


# ---------------------------------------------------------------- admin: conversations & handoffs


@app.get("/admin/api/{slug}/conversations")
def list_conversations(
    language: str | None = None,
    channel: str | None = None,
    principal: Principal = NeedsConversationsRead,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Recent conversations, optionally narrowed.

    The filters exist so the dashboard's language and channel rows can be
    clicked through to the conversations they count. A figure you cannot open
    is a figure you have to take on trust.
    """
    bank = principal.bank
    where = [Conversation.bank_id == bank.id]
    if language:
        where.append(Conversation.language == language)
    if channel:
        where.append(Conversation.channel == channel)
    convos = db.execute(
        select(Conversation).where(*where)
        .order_by(Conversation.created_at.desc()).limit(100)
    ).scalars().all()
    ids = [c.id for c in convos]

    # What each conversation was ABOUT, how long it ran, and whether it ended
    # up on somebody's desk. Without these the list is a hundred rows of
    # channel-and-timestamp: identical to each other, and unreadable at the
    # only volume that matters. Three bounded queries rather than a subquery
    # per row.
    previews: dict[str, str] = {}
    if ids:
        for cid, text in db.execute(
            select(Message.conversation_id, Message.text)
            .where(Message.conversation_id.in_(ids), Message.role == "user")
            .order_by(Message.created_at)
        ).tuples().all():
            # First one wins — the opening question is what the conversation
            # was about, and later turns are usually clarifications of it.
            previews.setdefault(cid, text)
    turns: dict[str, int] = (
        dict(
            db.execute(
                select(Message.conversation_id, func.count())
                .where(Message.conversation_id.in_(ids))
                .group_by(Message.conversation_id)
            ).tuples().all()
        )
        if ids else {}
    )
    escalated: set[str] = (
        {
            row
            for (row,) in db.execute(
                select(Handoff.conversation_id)
                .where(
                    Handoff.conversation_id.in_(ids),
                    Handoff.needs_person.is_(True),
                )
                .distinct()
            ).all()
        }
        if ids else set()
    )
    return [
        {
            "id": c.id, "channel": c.channel, "language": c.language,
            "created_at": iso(c.created_at),
            # Truncated here rather than in the browser: a list endpoint that
            # ships whole transcripts to render forty characters of each is
            # the same waste as the retrieval scan, on the same screen.
            "preview": (previews.get(c.id) or "")[:160],
            "turns": int(turns.get(c.id, 0)),
            "escalated": c.id in escalated,
        }
        for c in convos
    ]


@app.get("/admin/api/{slug}/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    principal: Principal = NeedsConversationsRead,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    bank = principal.bank
    convo = db.get(Conversation, conversation_id)
    if convo is None or convo.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown conversation")
    msgs = db.execute(
        select(Message).where(Message.conversation_id == convo.id).order_by(Message.created_at)
    ).scalars().all()
    return [
        {
            "role": m.role, "text": m.text, "intent": m.intent,
            "sources": m.sources, "created_at": iso(m.created_at),
        }
        for m in msgs
    ]


@app.get("/admin/api/{slug}/handoffs")
def list_handoffs(
    status: str = "open",
    department: str = "all",
    principal: Principal = NeedsHandoffsRead,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """The work queue. Defaults to open, oldest first.

    Newest-first is the wrong order for work: a customer who has been waiting
    three days for a callback outranks one who asked five minutes ago, and the
    old default buried them at the bottom of 200 rows. Closed handoffs keep
    newest-first, because that view is history rather than a queue.
    """
    bank = principal.bank
    if status not in {"open", "closed", "all"}:
        raise HTTPException(status_code=400, detail="status must be open, closed or all")

    # Only rows a person is expected to act on. A general-knowledge answer
    # files a row so the bank can see it has no content on the subject, but the
    # customer got a complete answer and left — those belong in Content Gaps,
    # and putting them here told an operator that nine people were waiting when
    # nobody was.
    query = select(Handoff).where(
        Handoff.bank_id == bank.id, Handoff.needs_person.is_(True)
    )
    if status != "all":
        query = query.where(Handoff.status == status)
    if department and department != "all":
        query = query.where(Handoff.department == department)
    # Urgent first, then oldest. Both halves matter: a theft report filed an
    # hour ago outranks a fee question from yesterday, and within one lane the
    # person who has waited longest must keep winning or the queue produces
    # the abandonment it exists to prevent.
    urgency = case((Handoff.priority == departments.URGENT, 0), else_=1)
    order = Handoff.created_at.asc() if status == "open" else Handoff.created_at.desc()

    rows = db.execute(
        query.order_by(urgency, order).limit(200)
    ).scalars().all()
    return [
        {
            "id": h.id, "reason": h.reason, "detail": h.detail, "status": h.status,
            "department": h.department, "priority": h.priority,
            "department_label": departments.label(h.department),
            "conversation_id": h.conversation_id, "created_at": iso(h.created_at),
            # Who to call. The whole point of a handoff queue is that someone
            # works it, and until now a row said a customer wanted a callback
            # without saying where to.
            "contact_name": h.contact_name, "contact_phone": h.contact_phone,
            "resolution": h.resolution,
            "resolved_at": iso(h.resolved_at),
        }
        for h in rows
    ]


# ---------------------------------------------------------------- importing


class IngestIn(BaseModel):
    """A URL to fetch, or something somebody pasted. Not both."""

    url: str | None = None
    html: str | None = None
    # Used only when the pasted content is plain text rather than markup —
    # copied text has no <title> and no headings to take a name from, and a
    # document called "Untitled page" is one nobody can find again.
    title: str = ""
    language: str = "en"
    category: str = "general"
    # Where pasted content came from. Optional, and only meaningful alongside
    # `html` — a fetched import already knows its own address.
    #
    # This exists because pasting is the NORMAL path here, not a fallback: most
    # Ethiopian bank sites build their pages in the browser, so a fetch returns
    # an empty shell and the operator copies the rendered page instead. Without
    # this field every document imported that way lands with no provenance,
    # which costs both of the things `documents.source_url` was added for —
    # answering a compliance reviewer's "where is this text from", and matching
    # a re-import to the document it should replace. Somebody who just copied a
    # page knows its address; asking for it is far cheaper than losing it.
    source_url: str | None = None


class IngestCommitIn(IngestIn):
    # Which of the proposed sections to actually write, by title. An import
    # that wrote everything it found would be the reason nobody uses it twice:
    # the first page always brings something the bank does not want.
    titles: list[str] = Field(default_factory=list)


# A bank's page, not a video. Enough for the longest tariff page anybody
# publishes and small enough that a hostile response cannot fill the instance.
MAX_IMPORT_BYTES = 3_000_000


def _fetch_page(url: str) -> str:
    """Fetch a page for import, or raise HTTPException.

    Thin on purpose — everything worth arguing about is in
    `ingest.check_url`, which is pure and separately tested. What is left here
    is the two bounds that a URL check cannot express: how long we wait, and
    how much we are willing to read.

    Redirects are NOT followed. A checked https address that 302s to
    http://169.254.169.254 would walk straight past the guard, and a bank's
    published page does not need a redirect to be readable.
    """
    import httpx

    try:
        safe = ingest.check_url(url)
    except ingest.UnsafeUrl as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        with httpx.Client(follow_redirects=False, timeout=10.0) as client:
            resp = client.get(safe, headers={"User-Agent": "OlinkBankAssist/1.0"})
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach that page: {exc}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"That page returned {resp.status_code}",
        )
    if resp.status_code >= 300:
        raise HTTPException(
            status_code=422,
            detail="That address redirects. Import the address it points to.",
        )
    if len(resp.content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="That page is too large to import")
    return resp.text


def _stated_source(raw: str | None) -> str | None:
    """The address an operator says pasted content came from, or None.

    Validated but never fetched. A rejected address fails the import rather
    than being dropped silently: somebody who typed one wants it recorded, and
    quietly storing nothing would leave them believing the document is
    attributed when it is not.
    """
    if raw is None or not raw.strip():
        return None
    try:
        return ingest.check_url(raw)
    except ingest.UnsafeUrl as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _proposed(payload: IngestIn) -> tuple[list[ingest.Section], str | None]:
    if payload.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Unsupported language")
    if payload.url and payload.html:
        raise HTTPException(
            status_code=422, detail="Give an address or some markup, not both"
        )
    if payload.url:
        markup = _fetch_page(payload.url)
        return ingest.sections(markup, fallback_title=""), payload.url.strip()
    if payload.html:
        pasted = payload.html
        # Held to the same rule as a fetched address even though nothing is
        # requested from it. One notion of a legitimate page address is easier
        # to reason about than two, and a provenance line that a reviewer
        # cannot open is not provenance.
        stated = _stated_source(payload.source_url)
        if not ingest.looks_like_markup(pasted):
            # Somebody selected the page and copied it, which is the only
            # thing that works on a site that builds itself in the browser.
            return ingest.plain_text_section(pasted, payload.title), stated
        return ingest.sections(pasted, fallback_title=payload.title), stated
    raise HTTPException(status_code=422, detail="Nothing to import")


@app.post("/admin/api/{slug}/ingest/preview")
def ingest_preview(
    payload: IngestIn,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """What WOULD be imported, without importing any of it.

    The whole reason this is two endpoints. Nobody should write two hundred
    documents into the thing that answers their customers on the strength of a
    URL typed into a box — the first page a bank imports always brings a
    section they do not want, and finding that out afterwards means undoing it
    by hand.

    Each proposal says whether it is new or would replace something, so
    re-importing an updated page reads as five updates rather than five
    unexplained duplicates.
    """
    bank = principal.bank
    found, source = _proposed(payload)
    # When nothing came back, say WHY. "Nothing importable on that page" is
    # true and useless: the operator is looking at a page they can see has
    # content, with no idea whether to try a different page, a different
    # button, or give up on the feature.
    note = None
    if not found:
        markup = payload.html or ""
        if payload.url:
            markup = _fetch_page(payload.url)
        note = ingest.diagnose(markup, found)
    existing = {
        row.title: row
        for row in db.execute(
            select(Document).where(Document.bank_id == bank.id)
        ).scalars().all()
    }
    return {
        "source_url": source,
        "note": note,
        "sections": [
            {
                "title": s.title,
                "chars": s.chars,
                "preview": s.body[:280],
                "replaces": s.title in existing,
                # Flagged, never dropped. Every bank product page is somewhat
                # promotional — "open a savings account today and earn 7%" is
                # both marketing and the literal answer to a real question —
                # so whether sales copy belongs in a knowledge base is the
                # bank's judgement. The job here is to make that judgement
                # fast when there are two hundred sections to look at.
                "promotional": ingest.is_promotional(s.title, s.body),
            }
            for s in found
        ],
    }


@app.post("/admin/api/{slug}/ingest/commit")
def ingest_commit(
    payload: IngestCommitIn,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Write the sections the operator ticked. Nothing else.

    Re-fetches rather than trusting a body the browser round-tripped: what
    gets written to a bank's knowledge base should be what the server read,
    not what a client says the server read.

    Matched on title within the tenant, so a re-import UPDATES rather than
    duplicating. The alternative — always insert — produces a knowledge base
    holding last quarter's fee beside this quarter's, with nothing to say
    which is current, and the customer gets whichever one scores higher.
    """
    bank = principal.bank
    found, source = _proposed(payload)
    wanted = set(payload.titles)
    chosen = [s for s in found if s.title in wanted] if wanted else found
    if not chosen:
        raise HTTPException(status_code=422, detail="Nothing was selected")

    existing = {
        row.title: row
        for row in db.execute(
            select(Document).where(Document.bank_id == bank.id)
        ).scalars().all()
    }
    created, updated = 0, 0
    for section in chosen:
        doc = existing.get(section.title)
        if doc is None:
            doc = Document(
                bank_id=bank.id, title=section.title, content=section.body,
                category=payload.category, language=payload.language,
                source_url=source,
            )
            db.add(doc)
            db.flush()
            created += 1
        else:
            doc.content = section.body
            doc.language = payload.language
            doc.source_url = source or doc.source_url
            updated += 1
        reindex_document(db, doc)
    _audit(
        db, bank, "documents_imported", "bank", bank.id,
        {"source": source or "pasted", "created": created, "updated": updated},
        actor=principal.audit_actor,
    )
    db.commit()
    return {"created": created, "updated": updated}


# --------------------------------------------------------- curated answers


class FaqIn(BaseModel):
    question: str = Field(min_length=3, max_length=400)
    answer: str = Field(min_length=1)
    language: str = "en"
    status: str = "draft"


def _faq_row(row: Faq) -> dict[str, Any]:
    return {
        "id": row.id,
        "question": row.question,
        "answer": row.answer,
        "language": row.language,
        "status": row.status,
        "served": row.served,
        "approved_at": iso(row.approved_at),
        "updated_at": iso(row.updated_at),
        # Which answer this one was translated FROM. The panel groups a
        # question and its four translations by this; without it the download
        # would emit five unrelated rows per question, which is the exact
        # mistake the TSV exporter was written to fix.
        "source_faq_id": row.source_faq_id,
    }


@app.get("/admin/api/{slug}/faq")
def list_faq(
    status: str | None = None,
    principal: Principal = NeedsDocumentsRead,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Every curated answer, most-served first.

    Most-served rather than newest: the list is read to decide what to write
    next, and the answer carrying a thousand customers a month is the one
    whose wording is worth an argument.

    `status=published` is what the teller console asks for. A teller reading
    an answer aloud to a customer must be handed only wording the bank stands
    behind — a draft is somebody's half-written afternoon, and reading it out
    is precisely the harm draft status exists to prevent. Filtering here
    rather than in the browser means the drafts are never sent at all.
    """
    query = select(Faq).where(Faq.bank_id == principal.bank.id)
    if status is not None:
        if status not in ("draft", "published"):
            raise HTTPException(status_code=422, detail="Unknown status")
        query = query.where(Faq.status == status)
    rows = db.execute(
        query.order_by(Faq.served.desc(), Faq.updated_at.desc())
    ).scalars().all()
    return [_faq_row(r) for r in rows]


@app.get("/admin/api/{slug}/faq/suggestions")
def faq_suggestions(
    principal: Principal = NeedsDocumentsRead, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """What customers keep asking, and whether it has an approved answer yet.

    This is the loop. The assistant sees every question; the bank sees which
    ones repeat; whoever owns the wording writes it once and it is served
    verbatim from then on. Without this list the feature is a form nobody
    knows what to type into.

    Counted over the most recent traffic rather than all of it, because a
    question that was common last March and is not asked any more is not the
    one to spend an afternoon on.
    """
    bank = principal.bank
    rows = db.execute(
        select(Message.text, Conversation.language)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.bank_id == bank.id, Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(4000)
    ).tuples().all()

    counts: Counter[tuple[str, str]] = Counter()
    original: dict[tuple[str, str], str] = {}
    for text, language in rows:
        lang = language or bank.default_language
        # Greeting-stripped and normalised, so "Selam, how do I open an
        # account?" and "how do i open an account" are one row rather than
        # two neither of which looks frequent enough to bother with.
        asked, _ = classifier.strip_greeting(text)
        asked = asked or text
        if len(asked) < 8:
            continue        # "ok", "yes", "thanks" — not questions
        # Only what a curated answer could actually be SERVED for.
        #
        # The lookup in `respond()` sits behind every guardrail, so an answer
        # published for a greeting, a complaint, an account request or "can I
        # speak to a manager" is unreachable — it would sit in the admin
        # looking published and never reach a customer. Offering those here is
        # offering work that does nothing, and the operator who does it
        # concludes the feature is broken rather than that the suggestion was
        # wrong. Seen in production on the first real list.
        if classifier.classify_intent(asked) not in classifier.CURATABLE_INTENTS:
            continue
        k = (lang, faq.normalise(asked))
        counts[k] += 1
        original.setdefault(k, asked)

    have = {
        row.lookup: row
        for row in db.execute(
            select(Faq).where(Faq.bank_id == bank.id)
        ).scalars().all()
    }
    out = []
    for (lang, norm), n in counts.most_common(40):
        if n < 2:
            continue        # asked once is not a pattern
        existing = have.get(f"{lang}\x1f{norm}")
        out.append({
            "question": original[(lang, norm)],
            "language": lang,
            "asked": n,
            "faq_id": existing.id if existing else None,
            "status": existing.status if existing else None,
        })
    return out


@app.post("/admin/api/{slug}/faq", status_code=201)
def create_faq(
    payload: FaqIn,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Write an answer the bank stands behind.

    `documents.write`, the same bar as editing the knowledge base — because it
    is the same act. This text is served to customers verbatim, with no model
    between it and them, which if anything makes it the more consequential of
    the two.
    """
    bank = principal.bank
    if payload.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Unsupported language")
    if payload.status not in ("draft", "published"):
        raise HTTPException(status_code=422, detail="Unknown status")
    lookup = faq.key(payload.question, payload.language)
    if db.execute(
        select(Faq.id).where(Faq.bank_id == bank.id, Faq.lookup == lookup)
    ).first() is not None:
        # Refused, not silently merged. Two answers to one question is a
        # support call nobody can reproduce; a 409 is a sentence an operator
        # can act on.
        raise HTTPException(
            status_code=409, detail="There is already an answer for that question"
        )
    row = Faq(
        bank_id=bank.id, question=payload.question.strip(), lookup=lookup,
        answer=payload.answer.strip(), language=payload.language,
        status=payload.status,
    )
    if payload.status == "published":
        row.approved_by = principal.user.id if principal.user else None
        row.approved_at = datetime.now(UTC)
    db.add(row)
    db.flush()
    _audit(
        db, bank, "faq_created", "faq", row.id,
        {"question": row.question, "status": row.status},
        actor=principal.audit_actor,
    )
    db.commit()
    return _faq_row(row)


@app.put("/admin/api/{slug}/faq/{faq_id}")
def update_faq(
    faq_id: str,
    payload: FaqIn,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Edit or publish one.

    Re-approval is recorded on every publish, not only the first. An answer
    edited after approval and still carrying the original sign-off would be a
    record of somebody approving words they never read.
    """
    bank = principal.bank
    row = db.get(Faq, faq_id)
    if row is None or row.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown answer")
    if payload.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Unsupported language")
    if payload.status not in ("draft", "published"):
        raise HTTPException(status_code=422, detail="Unknown status")
    lookup = faq.key(payload.question, payload.language)
    clash = db.execute(
        select(Faq.id).where(
            Faq.bank_id == bank.id, Faq.lookup == lookup, Faq.id != row.id
        )
    ).first()
    if clash is not None:
        raise HTTPException(
            status_code=409, detail="Another answer already covers that question"
        )
    row.question = payload.question.strip()
    row.lookup = lookup
    row.answer = payload.answer.strip()
    row.language = payload.language
    was = row.status
    row.status = payload.status
    if payload.status == "published":
        row.approved_by = principal.user.id if principal.user else None
        row.approved_at = datetime.now(UTC)
    _audit(
        db, bank, "faq_updated", "faq", row.id,
        {"question": row.question, "from": was, "to": row.status},
        actor=principal.audit_actor,
    )
    db.commit()
    return _faq_row(row)


@app.delete("/admin/api/{slug}/faq/{faq_id}")
def delete_faq(
    faq_id: str,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    bank = principal.bank
    row = db.get(Faq, faq_id)
    if row is None or row.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown answer")
    _audit(
        db, bank, "faq_deleted", "faq", row.id,
        {"question": row.question}, actor=principal.audit_actor,
    )
    db.delete(row)
    db.commit()
    return {"deleted": True}


class FaqImportIn(BaseModel):
    """A copied FAQ page, and optionally which of its questions to keep."""

    text: str = Field(min_length=1)
    language: str = "en"
    # Empty means "everything found", matching the page importer. Selection is
    # by question rather than by index so that ticking a box and then editing
    # the pasted text cannot silently import a different answer than the one
    # on screen.
    questions: list[str] = Field(default_factory=list)


def _faq_proposed(payload: FaqImportIn, bank_id: str, db: Session) -> list[
    dict[str, Any]
]:
    if payload.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Unsupported language")
    existing = {
        row.lookup: row.status
        for row in db.execute(
            select(Faq).where(Faq.bank_id == bank_id)
        ).scalars().all()
    }
    out: list[dict[str, Any]] = []
    for pair in faq.pairs(payload.text):
        held = existing.get(faq.key(pair.question, payload.language))
        out.append({
            "question": pair.question,
            "answer": pair.answer,
            "chars": len(pair.answer),
            # Named rather than a boolean, because "you already answer this,
            # and it is live right now" is a different decision from "you have
            # a draft of this".
            "existing": held,
        })
    return out


@app.post("/admin/api/{slug}/faq/import/preview")
def faq_import_preview(
    payload: FaqImportIn,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """What a pasted FAQ page would become. Nothing is written.

    A bank's published FAQ is the best content it owns and the only content
    that arrives in exactly the shape this table wants — somebody has already
    chosen the questions that matter and written the approved answer to each.
    The reason a bank with forty published answers ends up with four curated
    is that the only way in was typing them back one at a time.
    """
    found = _faq_proposed(payload, principal.bank.id, db)
    note = None
    if not found:
        # Same doctrine as the page importer: an empty preview must say what
        # to do next, not leave somebody staring at a page they can see has
        # questions on it.
        note = (
            "No questions found. This reads each line that ends in a question "
            "mark as a question, and everything under it as the answer — so "
            "copy the questions and answers themselves rather than a list of "
            "links, and expand any collapsed ones first."
        )
    return {"pairs": found, "note": note}


@app.post("/admin/api/{slug}/faq/import")
def faq_import(
    payload: FaqImportIn,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Write the chosen questions as **drafts**.

    Drafts, always, and this is not a convenience default that can be
    relaxed later. `approved_by` is the entire difference between a curated
    answer and a cache with extra steps — publishing on import would put a
    bank's name on wording nobody at the bank has read, at the one point in
    this product where nothing downstream can catch a mistake.

    Existing answers are left alone rather than overwritten. An import that
    silently replaced a published answer would let a stale copy of a page undo
    a correction somebody made deliberately.
    """
    bank = principal.bank
    found = _faq_proposed(payload, bank.id, db)
    wanted = set(payload.questions)
    chosen = [p for p in found if p["question"] in wanted] if wanted else found
    if not chosen:
        raise HTTPException(status_code=422, detail="Nothing was selected")

    created, skipped = 0, 0
    for pair in chosen:
        if pair["existing"] is not None:
            skipped += 1
            continue
        db.add(Faq(
            bank_id=bank.id,
            question=pair["question"][:400],
            lookup=faq.key(pair["question"], payload.language),
            answer=pair["answer"],
            language=payload.language,
            status="draft",
        ))
        created += 1
    _audit(
        db, bank, "faq_imported", "bank", bank.id,
        {"created": created, "skipped": skipped, "language": payload.language},
        actor=principal.audit_actor,
    )
    db.commit()
    return {"created": created, "skipped": skipped}


class FaqPublishIn(BaseModel):
    """Which drafts to approve in one action."""

    # Empty means every language. Named explicitly in the normal case, so the
    # audit record says what somebody actually decided rather than "all".
    languages: list[str] = Field(default_factory=list)
    faq_ids: list[str] = Field(default_factory=list)


@app.post("/admin/api/{slug}/faq/publish")
def faq_publish(
    payload: FaqPublishIn,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Approve drafts in bulk, and record who did it.

    Eight hundred answers is not a queue anybody clears one row at a time, so
    without this the honest choice is between publishing nothing and clicking
    for an afternoon — and nothing is what actually happens.

    `approved_by` and `approved_at` are stamped exactly as the single-answer
    path stamps them. That is the whole point: bulk approval is still
    approval, and it must leave the same record a careful one-at-a-time pass
    would. The audit entry additionally counts how many of these were machine
    translations nobody had read, because the person running a linguist review
    later needs to know what went out and in which languages, and
    reconstructing that from timestamps afterwards is guesswork.
    """
    bank = principal.bank
    for code in payload.languages:
        if code not in SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=422, detail=f"Unsupported language {code}")

    query = select(Faq).where(Faq.bank_id == bank.id, Faq.status == "draft")
    if payload.languages:
        query = query.where(Faq.language.in_(payload.languages))
    if payload.faq_ids:
        query = query.where(Faq.id.in_(payload.faq_ids))
    rows = list(db.execute(query).scalars().all())

    now = datetime.now(UTC)
    by_language: dict[str, int] = {}
    machine = 0
    for row in rows:
        row.status = "published"
        row.approved_by = principal.user.id if principal.user else None
        row.approved_at = now
        by_language[row.language] = by_language.get(row.language, 0) + 1
        # Written by translate_curated rather than by a person. Counted, not
        # blocked — but counted, because "we published 640 machine
        # translations on the tenth" is the sentence a reviewer needs.
        if row.source_faq_id is not None:
            machine += 1
    _audit(
        db, bank, "faq_published_bulk", "bank", bank.id,
        {"published": len(rows), "by_language": by_language,
         "machine_translations": machine},
        actor=principal.audit_actor,
    )
    db.commit()
    return {
        "published": len(rows),
        "by_language": by_language,
        "machine_translations": machine,
    }


class FaqTranslateIn(BaseModel):
    """Which answers to render into which languages."""

    source_language: str = "en"
    # Empty means every language this product serves except the source.
    languages: list[str] = Field(default_factory=list)
    # Empty means every answer in the source language. Ids let a bank
    # translate the twenty questions people actually ask before paying for
    # the hundred and forty they do not.
    faq_ids: list[str] = Field(default_factory=list)


@app.post("/admin/api/{slug}/faq/translate")
def faq_translate(
    payload: FaqTranslateIn,
    principal: Principal = NeedsDocumentsWrite,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Draft every missing language for the bank's curated answers.

    A curated answer is only ever served for the language it was written in —
    `faq.key` includes the language — so an English-only table means an
    Amharic customer never gets a tier-1 hit at all. They still get an answer
    from retrieval, but they pay a model call for what an English speaker gets
    free and instant.

    Everything written here is a **draft**, and that is not the same caution
    as refusing to machine-translate. The point is to get a hundred and sixty
    answers into five languages TODAY, so a native speaker has something to
    correct instead of a blank sheet — `scripts/faq_export.py` writes exactly
    that sheet. Waiting for somebody at the bank to translate from nothing is
    how a language ships six months late or not at all.

    Existing rows are never overwritten. A translation already corrected by a
    reviewer must not be replaced by a fresh machine draft, which is the one
    way this could destroy real work.
    """
    bank = principal.bank
    if payload.source_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Unsupported source language")
    targets = payload.languages or [
        code for code in SUPPORTED_LANGUAGES if code != payload.source_language
    ]
    for code in targets:
        if code not in SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=422, detail=f"Unsupported language {code}")

    query = select(Faq).where(
        Faq.bank_id == bank.id, Faq.language == payload.source_language
    )
    if payload.faq_ids:
        query = query.where(Faq.id.in_(payload.faq_ids))
    sources = list(db.execute(query).scalars().all())

    # Keyed on what a translation IS — this answer, in that language — not on
    # its wording. A reviewer who corrects the translated question changes its
    # lookup key, and matching on that would write a second row beside the
    # correction rather than recognising it.
    covered = {
        (row.source_faq_id, row.language)
        for row in db.execute(select(Faq).where(Faq.bank_id == bank.id)).scalars()
        if row.source_faq_id
    }
    held = {
        row.lookup
        for row in db.execute(select(Faq).where(Faq.bank_id == bank.id)).scalars()
    }
    created, skipped, failed = 0, 0, 0
    for row in sources:
        for code in targets:
            if (row.id, code) in covered:
                skipped += 1
                continue
            try:
                question = llm.translate_curated(
                    row.question, code, LANGUAGE_NAMES[code], bank.name
                )
                answer = llm.translate_curated(
                    row.answer, code, LANGUAGE_NAMES[code], bank.name
                )
            except llm.LLMUnavailable:
                # One answer failing must not lose the batch. A miss here is a
                # row a reviewer fills in by hand, which is what they were
                # going to do for all of them anyway.
                failed += 1
                continue
            lookup = faq.key(question, code)
            if lookup in held:
                # Some other answer already occupies this key. Refused rather
                # than merged, for the same reason create_faq refuses: two
                # answers to one question is a support call nobody can
                # reproduce.
                skipped += 1
                continue
            held.add(lookup)
            covered.add((row.id, code))
            db.add(Faq(
                bank_id=bank.id, question=question[:400], lookup=lookup,
                answer=answer, language=code, status="draft",
                source_faq_id=row.id,
            ))
            created += 1
    _audit(
        db, bank, "faq_translated", "bank", bank.id,
        {"created": created, "skipped": skipped, "failed": failed,
         "languages": targets},
        actor=principal.audit_actor,
    )
    db.commit()
    return {"created": created, "skipped": skipped, "failed": failed}


@app.get("/admin/api/{slug}/integrations")
def integration_settings(
    principal: Principal = NeedsIntegrationsManage, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """What is currently wired up. Never the secrets.

    The settings screen shipped with empty fields whether or not anything was
    connected, which is worse than merely unhelpful here: the one control on
    that page decides where customers' names and phone numbers are delivered,
    and someone who cannot see the current value can disconnect it by saving a
    field they believed was already blank.

    The webhook URL is returned; its signing secret is not, and neither is the
    Telegram bot token. Both are shown once when set and never readable
    afterwards — a value the API will re-display is a value that ends up in a
    screenshot.
    """
    bank = principal.bank
    return {
        "handoff_webhook": {
            "connected": bool(bank.handoff_webhook_url),
            "url": bank.handoff_webhook_url,
            # So the screen can say the secret exists without revealing it.
            "has_secret": bool(bank.handoff_webhook_secret),
        },
        "telegram": {"connected": bool(bank.telegram_bot_token)},
        "viber": {"connected": bool(bank.viber_auth_token)},
        # Meta's callback is registered from Meta's dashboard, not by us, so
        # the panel has to show the operator what to paste there. The verify
        # token is not a secret in the signing sense — it only proves the
        # endpoint is ours during the handshake — but it is still per-tenant
        # and generated, never chosen.
        "meta": {
            "connected": bool(bank.meta_app_secret),
            "callback_url": f"{get_settings().app_base_url}/webhooks/meta/{bank.slug}",
            "verify_token": bank.meta_verify_token,
            "whatsapp": bool(
                bank.whatsapp_access_token and bank.whatsapp_phone_number_id
            ),
            "messenger": bool(bank.messenger_page_token),
            "instagram": bool(bank.instagram_access_token),
        },
        "sms": {
            "connected": bool(bank.sms_send_url),
            "callback_url": f"{get_settings().app_base_url}/webhooks/sms/{bank.slug}",
            "has_secret": bool(bank.sms_inbound_secret),
            "sender_id": bank.sms_sender_id,
        },
        # Every channel, with what each actually requires. Served rather than
        # written into the page so the answer to "can you do WhatsApp" is one
        # list, kept next to the code that would implement it.
        "channels": channels.catalogue(**_connected_channels(bank)),
        # The snippet to paste on the bank's own site. It was never shown
        # anywhere, so the one channel that is live by default had no
        # instructions attached to it.
        "embed": (
            f'<script src="{get_settings().app_base_url}/embed.js" '
            f'data-bank="{bank.slug}" data-color="{bank.primary_color}" '
            f"defer></script>"
        ),
        "branding": {
            "primary_color": bank.primary_color,
            "logo_url": bank.logo_url,
            "short_name": bank.short_name,
            "legal_name": bank.name,
            "display_name": bank.display_name,
        },
    }


class BrandingIn(BaseModel):
    # Blank clears it and falls back to the registered name.
    short_name: str | None = Field(default=None, max_length=64)
    # #rgb or #rrggbb. Validated because it is interpolated straight into a CSS
    # custom property in both the panel and the customer-facing widget, and an
    # unchecked string there is a stylesheet injection on a bank's own site.
    primary_color: str = Field(pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    logo_url: str | None = Field(default=None, max_length=500)


@app.put("/admin/api/{slug}/branding")
def set_branding(
    payload: BrandingIn,
    principal: Principal = NeedsIntegrationsManage,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The bank's own colour and logo, editable without a deploy.

    Seeded values are our reading of a bank's public site, which is a guess
    however carefully it is made — the shade sampled from a screenshot is not
    the one in the brand book. Rather than have every correction be a code
    change, the tenant sets it here and both the admin panel and the widget
    follow immediately.

    https only for the logo: the widget is embedded on the bank's own pages,
    and an http image there turns their padlock into a mixed-content warning.
    """
    bank = principal.bank
    logo = (payload.logo_url or "").strip() or None
    if logo is not None and not logo.startswith("https://"):
        raise HTTPException(status_code=422, detail="Logo URL must be https")

    bank.primary_color = payload.primary_color
    bank.logo_url = logo
    bank.short_name = (payload.short_name or "").strip() or None
    _audit(db, bank, "branding_updated", "bank", bank.id,
           {"primary_color": payload.primary_color, "logo_url": logo,
            "short_name": bank.short_name},
           actor=principal.audit_actor)
    db.commit()
    return {
        "primary_color": bank.primary_color,
        "logo_url": bank.logo_url,
        "short_name": bank.short_name,
        "display_name": bank.display_name,
    }


@app.get("/admin/api/{slug}/activity")
def recent_activity(
    limit: int = 12,
    principal: Principal = NeedsAnalyticsRead,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """What people have been doing in this panel, most recent first.

    Only worth building because `audit_log.actor` became a person in the
    authorization change — before that every row said "admin", and a feed over
    it would have been a list of identical entries.

    The actor is resolved to a name here rather than in the browser, so the
    panel does not have to fetch the whole user list to render a feed. An id
    that no longer resolves is shown as-is rather than dropped: an audit trail
    that hides the entries it cannot pretty-print is not an audit trail.
    """
    bank = principal.bank
    # Sign-ins are excluded from this feed and only from this feed. They are
    # still written to audit_log, and the Team screen shows each person's last
    # sign-in — but on a busy morning they crowd out every content and queue
    # change, and a panel that is eight identical "signed in" rows tells a
    # reader nothing. This answers "what changed", not "who was here".
    rows = db.execute(
        select(AuditLog)
        .where(AuditLog.bank_id == bank.id, AuditLog.action != "admin_login")
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(max(1, min(limit, 50)))
    ).scalars().all()

    ids = {r.actor for r in rows if r.actor != TOKEN_ACTOR}
    people = {
        u.id: (u.display_name or u.email)
        for u in db.execute(select(User).where(User.id.in_(ids))).scalars()
    } if ids else {}

    return [
        {
            "action": r.action,
            "entity_type": r.entity_type,
            "actor": (
                "Admin token" if r.actor == TOKEN_ACTOR
                else people.get(r.actor, r.actor)
            ),
            # So the panel can mark the break-glass rows rather than passing
            # them off as a colleague.
            "by_token": r.actor == TOKEN_ACTOR,
            "at": iso(r.created_at),
        }
        for r in rows
    ]


@app.get("/admin/api/{slug}/audit")
def audit_log(
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    actor: str | None = None,
    principal: Principal = NeedsAuditRead,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The full record of who did what, for an access review.

    Distinct from `/activity`, which is the dashboard's feed. That one drops
    sign-ins and caps at a dozen because it answers "what changed lately"; this
    one answers "show me everything this person did" and drops nothing. A
    review that silently omits a category of event is not a review, and sign-ins
    are usually the first thing asked about.

    Paged rather than capped, and the total is returned alongside, because "50
    entries" and "50 of 4,300 entries" are different answers and only one of
    them is honest about what is being looked at.
    """
    bank = principal.bank
    where = [AuditLog.bank_id == bank.id]
    if action:
        where.append(AuditLog.action == action)
    if actor:
        where.append(AuditLog.actor == actor)

    total = db.execute(
        select(func.count()).select_from(AuditLog).where(*where)
    ).scalar_one()
    rows = db.execute(
        select(AuditLog)
        .where(*where)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(max(1, min(limit, 500)))
        .offset(max(0, offset))
    ).scalars().all()

    # Resolved here rather than in the browser, and only for the ids on this
    # page — a review of a busy tenant should not pull every user row to label
    # fifty lines.
    ids = {r.actor for r in rows if r.actor != TOKEN_ACTOR}
    people = {
        u.id: {"name": u.display_name or u.email, "email": u.email}
        for u in db.execute(select(User).where(User.id.in_(ids))).scalars()
    } if ids else {}

    def _who(actor_id: str) -> dict[str, Any]:
        if actor_id == TOKEN_ACTOR:
            return {"name": "Admin token", "email": None, "by_token": True}
        # An id that no longer resolves is shown as itself. An audit trail that
        # hides the entries it cannot pretty-print is not an audit trail.
        person = people.get(actor_id)
        return {
            "name": person["name"] if person else actor_id,
            "email": person["email"] if person else None,
            "by_token": False,
        }

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        # Every distinct action present for this tenant, so the filter offers
        # what exists rather than a hardcoded list that drifts from it.
        "actions": sorted(
            a for (a,) in db.execute(
                select(AuditLog.action)
                .where(AuditLog.bank_id == bank.id)
                .group_by(AuditLog.action)
            ).all()
        ),
        "entries": [
            {
                "id": r.id,
                "at": iso(r.created_at),
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "actor": _who(r.actor),
                # The raw id as well as the label, so "show only this person"
                # filters on identity. Two colleagues can share a display name
                # and an audit filter that merged them would be worse than no
                # filter at all.
                "actor_id": r.actor,
                "metadata": r.log_metadata or {},
            }
            for r in rows
        ],
    }


@app.get("/admin/api/{slug}/content-gaps")
def content_gaps(
    principal: Principal = NeedsGapsRead, db: Session = Depends(get_db)
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
    bank = principal.bank
    # Joined to the conversation for its language. Which language a gap was
    # asked in decides which language the article has to be written in, and
    # without it the page can rank the work but not assign it.
    rows = db.execute(
        select(Handoff, Conversation.language)
        .join(Conversation, Conversation.id == Handoff.conversation_id, isouter=True)
        .where(Handoff.bank_id == bank.id)
        .where(Handoff.reason.in_(["unanswered_question", "answered_from_general_knowledge"]))
        .order_by(Handoff.created_at.desc())
        .limit(1000)
    ).all()

    grouped: dict[str, dict[str, Any]] = {}
    for h, language in rows:
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
                "languages": {},
                "examples": [],
                "last_asked": iso(h.created_at),
            },
        )
        gap["count"] += 1
        if language:
            gap["languages"][language] = gap["languages"].get(language, 0) + 1
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
    principal: Principal = NeedsAnalyticsRead,
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
    bank = principal.bank
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

    # --- the same figures for the window before this one ---------------
    #
    # So the dashboard can say "up from 71 last month" instead of drawing an
    # arrow whose baseline nobody can name. A comparison is only worth showing
    # if the reader can say what it is against.
    #
    # Null when there is nothing to compare with — an all-time view has no
    # preceding window, and a tenant in its first month would otherwise show a
    # triumphant +100% against a period when the product was not installed.
    previous: dict[str, Any] | None = None
    if since is not None:
        prior_start = since - timedelta(days=days)
        prior = [Message.created_at >= prior_start, Message.created_at < since]
        prior_rows = db.execute(
            select(Message.outcome, func.count())
            .where(Message.bank_id == bank.id, Message.role == "assistant")
            .where(*prior)
            .group_by(Message.outcome)
        ).all()
        prior_counts = {outcome: n for outcome, n in prior_rows if outcome}
        prior_substantive = sum(prior_counts.get(o, 0) for o in agent_module.SUBSTANTIVE)
        prior_resolved = sum(prior_counts.get(o, 0) for o in agent_module.RESOLVED)
        prior_answered = prior_counts.get(agent_module.ANSWERED, 0)
        prior_conversations = db.execute(
            select(func.count()).select_from(Conversation).where(
                Conversation.bank_id == bank.id,
                Conversation.created_at >= prior_start,
                Conversation.created_at < since,
            )
        ).scalar_one()
        # Only reported once the previous window actually contains something.
        # A first-ever month compared against silence is not a trend.
        if prior_conversations or prior_substantive:
            previous = {
                "conversations": prior_conversations,
                "substantive_questions": prior_substantive,
                "resolved_without_a_person": prior_resolved,
                "answered_from_own_content": prior_answered,
                "deflection_rate": round(prior_resolved / prior_substantive, 4)
                if prior_substantive else None,
                "own_content_rate": round(prior_answered / prior_substantive, 4)
                if prior_substantive else None,
            }

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
    # Every language the assistant supports, including those nobody has used
    # yet. A panel that lists only what has been spoken answers "what came in";
    # a bank looking at it is usually asking the other question — "are we
    # covered" — and Tigrinya missing from the list reads as unsupported
    # rather than as unused. Zero here is a real count, not a rate with no
    # denominator, so showing it states a fact rather than implying a failure.
    seen = {row["language"] for row in languages}
    for code in SUPPORTED_LANGUAGES:
        if code not in seen:
            languages.append(
                {"language": code, "name": LANGUAGE_NAMES[code], "count": 0}
            )
    languages.sort(key=lambda row: (-int(row["count"]), str(row["language"])))

    # What happened when someone asked in each language — the same idea as
    # top_topics' outcome breakdown, joined through Conversation because
    # language lives there, not on Message. outcome is written to the user
    # row of a turn too (see agent.py), so this filters exactly the way
    # top_topics does: substantive questions only, never greetings or the
    # contact exchange.
    language_outcome_rows = db.execute(
        select(Conversation.language, Message.outcome, func.count())
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.bank_id == bank.id,
            Message.role == "user",
            Message.outcome.in_(agent_module.SUBSTANTIVE),
        )
        .where(*_window(Message.created_at))
        .group_by(Conversation.language, Message.outcome)
    ).all()
    language_outcomes: dict[str, dict[str, int]] = {}
    for lang, outcome, n in language_outcome_rows:
        language_outcomes.setdefault(lang or "unknown", {})[outcome] = n
    for row in languages:
        row["outcomes"] = language_outcomes.get(row["language"], {})

    # Every channel in the catalogue, whether or not anyone has used it —
    # deliberately not just the ones GROUP BY returns.
    #
    # A breakdown built from traffic alone cannot answer the question a bank
    # is actually asking. "Web: 100%" and "WhatsApp is not connected yet" are
    # different facts, and a chart drawn only from rows that exist renders
    # both as the same thing: an absence. The second fact is the one worth
    # money, so the catalogue is the spine here and the counts are folded in.
    #
    # Named `channel_rows` rather than `channels`: assigning to `channels`
    # would shadow the imported module for the whole function body, and the
    # catalogue call below needs the module.
    channel_counts = {
        channel: n
        for channel, n in db.execute(
            select(Conversation.channel, func.count())
            .where(Conversation.bank_id == bank.id)
            .where(*_window(Conversation.created_at))
            .group_by(Conversation.channel)
        ).all()
    }
    catalogue = channels.catalogue(**_connected_channels(bank))
    channel_rows = [
        {
            "channel": entry["key"],
            "name": entry["name"],
            "status": entry["status"],
            "count": int(channel_counts.pop(entry["key"], 0)),
        }
        for entry in catalogue
    ]
    # Anything in the data but not in the catalogue. Should be empty; if it is
    # ever not, silently dropping real conversations from the totals would be
    # worse than showing a row with a key for a name.
    channel_rows.extend(
        {
            "channel": key or "unknown",
            "name": key or "Unknown",
            "status": channels.LIVE,
            "count": int(n),
        }
        for key, n in sorted(channel_counts.items(), key=lambda kv: -int(kv[1]))
    )
    # Busiest first, then by how close a channel is to carrying traffic, then
    # catalogue order — so the panel reads as "what is working, then what you
    # could turn on next" rather than as an alphabet.
    _status_rank = {channels.LIVE: 0, channels.AVAILABLE: 1, channels.PLANNED: 2}
    _catalogue_order = {entry["key"]: i for i, entry in enumerate(catalogue)}
    channel_rows.sort(
        key=lambda row: (
            -int(row["count"]),
            _status_rank.get(str(row["status"]), 3),
            _catalogue_order.get(str(row["channel"]), 99),
        )
    )

    # --- conversations per day ----------------------------------------
    #
    # Counted in Python from the rows' dates rather than with a SQL date
    # function, because date truncation is spelled differently in SQLite and
    # Postgres and the dashboard is not worth a dialect branch.
    #
    # Days with no conversations are filled in as zero. Without that, a quiet
    # weekend simply vanishes from the axis and the line closes the gap, which
    # draws a busy Friday and a busy Monday as one continuous slope — a picture
    # of activity that did not happen.
    started = db.execute(
        select(Conversation.created_at)
        .where(Conversation.bank_id == bank.id)
        .where(*_window(Conversation.created_at))
    ).scalars().all()
    per_day: dict[str, int] = {}
    for ts in started:
        per_day[ts.date().isoformat()] = per_day.get(ts.date().isoformat(), 0) + 1
    if days > 0:
        span = [
            (datetime.now(UTC).date() - timedelta(days=offset)).isoformat()
            for offset in range(days - 1, -1, -1)
        ]
    else:
        span = sorted(per_day)
    daily = [{"date": d, "conversations": per_day.get(d, 0)} for d in span]

    # --- what customers actually asked --------------------------------
    # Grouped by content signature, the same way content gaps are, so the two
    # reports name the same topic the same way.
    #
    # Filtered on the recorded outcome, never on the guessed intent. A reply of
    # "Oli 0911234567" to the contact request classifies as an ordinary
    # question, so an intent filter ranked a customer's name and phone number
    # as a top topic — wrong as analytics, and personal data surfacing in the
    # one report most likely to be exported and shown around.
    # outcome joins the same row: the Most Asked panel shows what happened to
    # each topic inline (answered / couldn't answer / handed to a person)
    # rather than only a question and a count, so a bank doesn't have to leave
    # the panel to learn whether its top question is actually being answered.
    question_rows = db.execute(
        select(Message.text, Message.outcome)
        .where(
            Message.bank_id == bank.id,
            Message.role == "user",
            Message.outcome.in_(agent_module.SUBSTANTIVE),
        )
        .where(*_window(Message.created_at))
        .order_by(Message.created_at.desc())
        .limit(2000)
    ).all()

    topics: dict[str, dict[str, Any]] = {}
    for text, outcome in question_rows:
        # Scrubbed before the signature is computed, so a volunteered number
        # can reach neither the grouping key nor the example.
        question = redact_contact((text or "").strip())
        if not question:
            continue
        key = content_signature(question) or question.lower()
        topic = topics.setdefault(
            key, {"signature": key, "count": 0, "example": question, "outcomes": {}}
        )
        topic["count"] += 1
        topic["outcomes"][outcome] = topic["outcomes"].get(outcome, 0) + 1
    top_topics = sorted(topics.values(), key=lambda t: (-int(t["count"]), str(t["signature"])))

    # --- the handoff queue, as work rather than history ---------------
    handoff_rows = db.execute(
        select(Handoff.status, Handoff.contact_phone)
        # Same filter as the queue, and it has to be the same or the dashboard
        # would advertise a number of waiting customers the queue cannot show.
        .where(Handoff.bank_id == bank.id, Handoff.needs_person.is_(True))
        .where(*_window(Handoff.created_at))
    ).all()
    open_handoffs = [h for h in handoff_rows if h.status == "open"]
    reachable = sum(1 for h in open_handoffs if h.contact_phone)

    return {
        # The bank's own name, not its slug. This report is printed and put in
        # front of people who have never seen the slug, and a page headed "cbe"
        # reads like an internal debug screen rather than their report.
        "bank_name": bank.display_name,
        "bank_legal_name": bank.name,
        "window_days": days,
        "since": iso(since),
        "conversations": conversations,
        "daily": daily,
        # The equivalent window immediately before this one, or null when there
        # is nothing honest to compare against.
        "previous": previous,
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
        "channels": channel_rows,
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


class HandoffCloseIn(BaseModel):
    resolution: str | None = Field(default=None, max_length=2000)


def _get_handoff(db: Session, bank: Bank, handoff_id: str) -> Handoff:
    handoff = db.get(Handoff, handoff_id)
    if handoff is None or handoff.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown handoff")
    return handoff


@app.post("/admin/api/{slug}/handoffs/{handoff_id}/close")
def close_handoff(
    handoff_id: str,
    body: HandoffCloseIn | None = None,
    principal: Principal = NeedsHandoffsResolve,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Close a handoff, optionally recording what was done about it.

    The body stays optional so closing without a note still works — an
    operator clearing an obvious duplicate should not be forced to write
    prose, and requiring it would only produce a queue full of "done".
    """
    bank = principal.bank
    handoff = _get_handoff(db, bank, handoff_id)
    handoff.status = "closed"
    handoff.resolved_at = datetime.now(UTC)
    # Who closed it, when there is a who. Left null for the break-glass token
    # rather than filled with a placeholder: "we do not know" is a true
    # statement and "admin" would not be.
    handoff.resolved_by = principal.user.id if principal.user is not None else None
    if body is not None and body.resolution:
        handoff.resolution = body.resolution.strip() or None
    # The note may quote the customer, so it is audited as a fact rather than
    # a value — same rule as chat text everywhere else.
    _audit(
        db, bank, "handoff_closed", "handoff", handoff.id,
        {"had_resolution": bool(handoff.resolution)},
        actor=principal.audit_actor,
    )
    db.commit()
    return {"status": "closed", "resolution": handoff.resolution}


class HandoffDepartmentIn(BaseModel):
    department: str


@app.put("/admin/api/{slug}/handoffs/{handoff_id}/department")
def move_handoff(
    handoff_id: str,
    payload: HandoffDepartmentIn,
    principal: Principal = NeedsHandoffsResolve,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Move an escalation to the desk that actually owns it.

    The rules will be wrong sometimes — they are rules — and the operator who
    notices is the one holding the row. One click, and the correction is
    audited: the log of what got moved, and from where to where, is the only
    honest way to find out which rule is wrong. A categoriser nobody can
    correct trains a queue to be ignored instead.
    """
    bank = principal.bank
    handoff = db.get(Handoff, handoff_id)
    if handoff is None or handoff.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown escalation")
    if payload.department not in departments.DEPARTMENTS:
        # Refused rather than coerced to `general`: a typo in a client that
        # silently dropped the row onto the catch-all desk would look like the
        # move worked, and the row would be somewhere nobody expected.
        raise HTTPException(
            status_code=422, detail=f"Unknown desk: {payload.department}"
        )
    was = handoff.department
    handoff.department = payload.department
    _audit(
        db, bank, "handoff_moved", "handoff", handoff.id,
        {"from": was, "to": payload.department}, actor=principal.audit_actor,
    )
    db.commit()
    return {
        "id": handoff.id,
        "department": handoff.department,
        "department_label": departments.label(handoff.department),
    }


@app.get("/admin/api/{slug}/handoffs/desks")
def handoff_desks(
    principal: Principal = NeedsHandoffsRead, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """Every desk, with how much open work is sitting on it.

    Returned even for desks with nothing waiting, and in a fixed order. A list
    that only shows the busy desks reorders itself as the day goes on, so the
    operator who has learned where their queue sits has to re-find it every
    time they look.
    """
    bank = principal.bank
    counts: dict[str, int] = dict(
        db.execute(
            select(Handoff.department, func.count())
            .where(
                Handoff.bank_id == bank.id,
                Handoff.needs_person.is_(True),
                Handoff.status == "open",
            )
            .group_by(Handoff.department)
        ).tuples().all()
    )
    urgent: dict[str, int] = dict(
        db.execute(
            select(Handoff.department, func.count())
            .where(
                Handoff.bank_id == bank.id,
                Handoff.needs_person.is_(True),
                Handoff.status == "open",
                Handoff.priority == departments.URGENT,
            )
            .group_by(Handoff.department)
        ).tuples().all()
    )
    return [
        {
            "department": desk,
            "label": departments.label(desk),
            "open": int(counts.get(desk, 0)),
            "urgent": int(urgent.get(desk, 0)),
        }
        for desk in departments.DEPARTMENTS
    ]


@app.post("/admin/api/{slug}/handoffs/{handoff_id}/reopen")
def reopen_handoff(
    handoff_id: str, principal: Principal = NeedsHandoffsResolve, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Put a handoff back in the queue.

    Closing is the only irreversible action in this panel otherwise, and the
    realistic case is mundane: nobody picked up. The previous resolution is
    left in place — it is the record of the attempt that did not work.
    """
    bank = principal.bank
    handoff = _get_handoff(db, bank, handoff_id)
    handoff.status = "open"
    handoff.resolved_at = None
    _audit(db, bank, "handoff_reopened", "handoff", handoff.id, None,
           actor=principal.audit_actor)
    db.commit()
    return {"status": "open"}


# ------------------------------------------------------------ teller sessions
#
# The HTTP surface for tier 3. See docs/video-teller.md.
#
# The media layer is deliberately absent: no channel is minted, no token is
# issued, and `channel` stays null. That is not an oversight — LiveKit
# credentials do not exist yet, and a token-minting path validated against a
# mock is exactly how a security-critical integration ships broken. What is
# here is everything the media layer will hang off: who asked, who is waiting,
# who claimed it, and what they verified.


class SessionRequestIn(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=36)
    # audio | video. Audio is the default deliberately — outside Addis it is
    # the common case, and a default of video would quietly make the product
    # worse for the customers with the worst connections.
    media: str = Field(default="audio")


class SessionVerifyIn(BaseModel):
    checks: list[str] = Field(default_factory=list)
    # The number the teller read off the ID. Only its last four digits are
    # kept — see verification.tail — so this field is transient by design.
    fayda_number: str | None = Field(default=None, max_length=40)


class SessionEndIn(BaseModel):
    resolution: str | None = Field(default=None, max_length=4000)


def first_name(display_name: str | None) -> str | None:
    """The name a customer is told, and no more of it.

    A first name, never the full one. Both directions of that matter:

    - A voice with no name at all is a call centre. "Meron from Demo Bank" is
      a person who is accountable for what they say, and the customer reported
      the current screen — a nameless "teller" — as the thing that felt wrong.
    - A SURNAME is what turns an ordinary support call into a person who can
      be looked up, turned up at, or impersonated to a colleague. Bank staff
      take calls from people who are angry about money. The trust is in the
      first name; the risk is all in the rest.

    Returns None for a blank, so the caller falls back to the generic label
    rather than rendering an empty gap where a name should be.
    """
    if not display_name:
        return None
    first = display_name.strip().split()
    return first[0] if first else None


def _session_public(
    session: TellerSession, teller_name: str | None = None
) -> dict[str, Any]:
    """What the CUSTOMER may see about their own session.

    Deliberately not the teller's user id and not the verification reference.
    A customer needs to know where they are in the process and what the person
    they are about to speak to can help with; everything else on the row is
    the bank's internal record.
    """
    return {
        "id": session.id,
        "state": session.state,
        "scope": session.scope,
        "media": session.media,
        # Who they are talking to, first name only — see `first_name`. Null
        # until somebody has claimed the session, because until then there is
        # nobody to name and inventing one would be worse than the gap.
        "teller_name": teller_name,
        # What this session can actually cover, so the customer is told the
        # boundary BEFORE they wait rather than after. Someone who queues for
        # ten minutes to ask for a transfer and is refused live has had a
        # worse experience than the assistant refusing instantly.
        "can_help_with": teller.capabilities(session.scope),
    }


def _teller_first_name(db: Session, session: TellerSession) -> str | None:
    """The claiming teller's first name, or None while nobody has claimed it."""
    if session.teller_user_id is None:
        return None
    user = db.get(User, session.teller_user_id)
    return first_name(user.display_name) if user is not None else None


def _session_public_queued(
    db: Session, bank: Bank, session: TellerSession
) -> dict[str, Any]:
    """The customer's view, plus their place in the queue when they're waiting.

    Shared by the create and the poll routes rather than living only on the
    poll. Returning it from only one of them left the customer looking at a
    spinner with no number until the first poll landed — three seconds of the
    exact screen this panel exists to avoid. A number beats a spinner: someone
    told they are third will wait; someone shown a spinner leaves.
    """
    data = _session_public(session, _teller_first_name(db, session))
    if session.state == teller.QUEUED:
        data["ahead"] = db.execute(
            select(func.count())
            .select_from(TellerSession)
            .where(
                TellerSession.bank_id == bank.id,
                TellerSession.state == teller.QUEUED,
                TellerSession.requested_at < session.requested_at,
            )
        ).scalar_one()
    return data


def _session_admin(db: Session, session: TellerSession) -> dict[str, Any]:
    """What a teller or supervisor sees. Adds the internal record."""
    data = _session_public(session, _teller_first_name(db, session))
    # The language the customer has been chatting in. A teller opening a
    # session needs to know whether to greet in Amharic or Afaan Oromoo before
    # they speak, not after — and the conversation already knows.
    conversation = db.get(Conversation, session.conversation_id)
    data.update(
        {
            "language": conversation.language if conversation is not None else None,
            "conversation_id": session.conversation_id,
            "handoff_id": session.handoff_id,
            "teller_user_id": session.teller_user_id,
            "verified_method": session.verified_method,
            "verified_ref": session.verified_ref,
            "waited_seconds": session.waited_seconds,
            "requested_at": iso(session.requested_at),
            "resolution": session.resolution,
        }
    )
    return data


@app.post("/chat/{slug}/teller-session", status_code=201)
def request_teller_session(
    slug: str, payload: SessionRequestIn, request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A customer asking to speak to a person.

    THE ONLY WAY A SESSION COMES INTO EXISTENCE, and it is called by the
    customer's own chat. There is deliberately no route that creates a session
    addressed at a customer: if people are trained to accept incoming calls
    "from the bank", that becomes a fraud vector pointed at exactly the
    customers least able to spot it. See docs/video-teller.md §2.

    Unauthenticated, like /chat itself — the customer has no account with us.
    Rate limited on the same limiter for the same reason.
    """
    client_ip = request.client.host if request.client else "unknown"
    limiter: SlidingWindowLimiter = request.app.state.ip_limiter
    if not limiter.allow(f"{slug}:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many requests, please slow down")

    bank = _get_bank(db, slug)
    # Enforced here, not only by hiding the button. The widget is public
    # JavaScript on a bank's own website — anyone can read it, find this route
    # and POST to it. A tenant that has not turned the feature on must not
    # accumulate a queue of customers no employee can see.
    if not bank.teller_enabled:
        raise HTTPException(
            status_code=409, detail="Live teller sessions are not enabled"
        )
    conversation = db.get(Conversation, payload.conversation_id)
    # Tenancy: a conversation id from another bank must not open a session here.
    if conversation is None or conversation.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown conversation")

    # One live session per conversation. Without this, a customer tapping the
    # button twice — or a flaky connection retrying — puts two of them in the
    # queue and two tellers answer the same person.
    existing = db.execute(
        select(TellerSession).where(
            TellerSession.conversation_id == conversation.id,
            TellerSession.state.notin_(tuple(teller.TERMINAL)),
        )
    ).scalars().first()
    if existing is not None:
        return _session_public_queued(db, bank, existing)

    session = TellerSession(
        bank_id=bank.id,
        conversation_id=conversation.id,
        media="video" if payload.media == "video" else "audio",
        # Straight to queued. Verification happens on the call with the teller
        # — see verification.py — so there is no automated check to wait for.
        # The `verifying` state stays in the machine for the Fayda OIDC path,
        # which will occupy it.
        state=teller.QUEUED,
        scope=teller.UNVERIFIED,
    )
    db.add(session)
    _audit(
        db, bank, "teller_session_requested", "teller_session", session.id,
        {"media": session.media}, actor="customer",
    )
    db.commit()
    return _session_public_queued(db, bank, session)


@app.get("/chat/{slug}/teller-session/{session_id}")
def poll_teller_session(
    slug: str, session_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Where am I in the queue? Polled by the customer's own chat."""
    bank = _get_bank(db, slug)
    session = db.get(TellerSession, session_id)
    if session is None or session.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown session")
    return _session_public_queued(db, bank, session)


def _join(session: TellerSession, *, identity: str, name: str) -> dict[str, Any]:
    """Everything a browser needs to get into the room, and nothing else."""
    creds = livekit.require()
    return {
        "url": creds.url,
        "token": livekit.access_token(
            session_id=session.id, identity=identity, name=name,
            # Both parties on a teller call publish. The read-only path exists
            # in livekit.py for a supervisor observing, which is not this.
            can_publish=True,
        ),
        "room": livekit.room_name(session.id),
        "identity": identity,
    }


@app.get("/chat/{slug}/teller-session/{session_id}/token")
def customer_join_token(
    slug: str, session_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """A join token for the customer, once a teller has actually taken them.

    Possession of the session id is the credential, exactly as it is for the
    poll route above — the id is a UUID4 and is only ever handed to the
    browser that created the session. Worth stating plainly rather than
    leaving implied, because this route mints a media credential and the poll
    route only reads state.

    Issued ONLY while the session is active. Before a teller claims it there
    is nobody to talk to, so a token then would be a live credential for an
    empty room sitting in a browser for the whole length of the queue wait.
    """
    bank = _get_bank(db, slug)
    session = db.get(TellerSession, session_id)
    if session is None or session.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown session")
    if session.state != teller.ACTIVE:
        raise HTTPException(status_code=409, detail="No teller on this session yet")
    if livekit.credentials() is None:
        raise HTTPException(status_code=503, detail="Video is not configured")
    return _join(session, identity=f"customer-{session.id}", name="Customer")


@app.get("/admin/api/{slug}/teller/sessions/{session_id}/token")
def teller_join_token(
    session_id: str,
    principal: Principal = NeedsTellerServe,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A join token for the teller who took this session.

    Deliberately not "anyone holding teller.serve". Only the person the
    session was claimed by may join it — otherwise every teller in the bank
    could drop into any live customer call, which is both a privacy problem
    and the kind of thing that is impossible to explain to a regulator after
    the fact. A colleague who needs to take over claims the session, and that
    is audited.
    """
    bank = principal.bank
    session = db.get(TellerSession, session_id)
    if session is None or session.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown session")
    if principal.user is None:
        # The break-glass token has no person behind it, and a live customer
        # call must be answerable to a named employee.
        raise HTTPException(
            status_code=403, detail="Sign in as a person to join a session"
        )
    if session.state != teller.ACTIVE:
        raise HTTPException(status_code=409, detail="That session is not active")
    if session.teller_user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Another teller has this session")
    if livekit.credentials() is None:
        raise HTTPException(status_code=503, detail="Video is not configured")
    return _join(
        session,
        identity=f"teller-{principal.user.id}",
        name=principal.user.display_name or "Teller",
    )


class SessionMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _thread(db: Session, session: TellerSession) -> list[dict[str, Any]]:
    """The whole conversation, assistant turns included.

    Deliberately the whole thing rather than only what was said on the call:
    the customer explained their problem to the assistant before asking for a
    person, and a chat panel that starts blank makes them explain it twice.
    """
    rows = db.execute(
        select(Message)
        .where(Message.conversation_id == session.conversation_id)
        .order_by(Message.created_at, Message.id)
    ).scalars().all()
    return [
        {
            "id": m.id, "role": m.role, "text": m.text,
            "at": iso(m.created_at),
        }
        for m in rows
    ]


def _live_session(db: Session, bank: Bank, session_id: str) -> TellerSession:
    session = db.get(TellerSession, session_id)
    if session is None or session.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown session")
    if session.state != teller.ACTIVE:
        raise HTTPException(status_code=409, detail="That session is not active")
    return session


@app.get("/chat/{slug}/teller-session/{session_id}/messages")
def customer_thread(
    slug: str, session_id: str, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """The conversation, polled by the customer during a call."""
    bank = _get_bank(db, slug)
    return _thread(db, _live_session(db, bank, session_id))


@app.post("/chat/{slug}/teller-session/{session_id}/messages", status_code=201)
def customer_says(
    slug: str, session_id: str, payload: SessionMessageIn, request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The customer typing to the teller, mid-call.

    THE ASSISTANT DOES NOT ANSWER THIS. That is the entire difference from
    `POST /chat/{slug}` and the reason this is a separate route rather than a
    flag on that one: a bot replying over the top of a human who is mid-
    sentence is the single worst thing this feature could do, and a flag is
    something a future change can get wrong. Here there is no code path to the
    agent at all.

    Rate limited on the shared IP limiter, like every other unauthenticated
    write.
    """
    client_ip = request.client.host if request.client else "unknown"
    limiter: SlidingWindowLimiter = request.app.state.ip_limiter
    if not limiter.allow(f"{slug}:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many requests, please slow down")

    bank = _get_bank(db, slug)
    session = _live_session(db, bank, session_id)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Empty message")
    db.add(
        Message(
            conversation_id=session.conversation_id, bank_id=bank.id,
            role="user", text=text,
        )
    )
    db.commit()
    return _thread(db, session)[-1]


@app.get("/admin/api/{slug}/teller/sessions/{session_id}")
def teller_session_state(
    session_id: str,
    principal: Principal = NeedsTellerServe,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """This session as the database has it, polled by the open call room.

    Deliberately NOT `_live_session`: the whole point is to be able to read a
    session that has just STOPPED being active. A route that 409s the moment
    the call ends cannot be the one that tells the teller it ended.

    This exists because of a field report. A customer hung up and the teller's
    screen stayed in the call — a live session with nobody on the other end.
    LiveKit's own participant-left event is best-effort: a phone that loses
    signal, gets backgrounded, or is simply switched off produces no clean
    disconnect, and a browser that never hears it waits out a timeout it
    cannot see. The database always knows. Polling it is how the teller finds
    out for certain rather than eventually.
    """
    bank = principal.bank
    session = db.get(TellerSession, session_id)
    if session is None or session.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown session")
    # The claiming teller only, matching every other route on this session —
    # a finished session is still a record of a named customer's business.
    if principal.user is None or session.teller_user_id != principal.user.id:
        raise HTTPException(
            status_code=403, detail="That session belongs to another teller"
        )
    return _session_admin(db, session)


@app.get("/admin/api/{slug}/teller/sessions/{session_id}/messages")
def teller_thread(
    session_id: str,
    principal: Principal = NeedsTellerServe,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """The conversation as the teller sees it, polled during the call.

    The whole thread, assistant turns included. The customer explained their
    problem before asking for a person, and a teller who cannot see that makes
    them explain it twice — which is the experience this product exists to
    replace.
    """
    bank = principal.bank
    session = _live_session(db, bank, session_id)
    if principal.user is None or session.teller_user_id != principal.user.id:
        raise HTTPException(
            status_code=403, detail="Only the teller on this session can read it"
        )
    return _thread(db, session)


@app.post("/admin/api/{slug}/teller/sessions/{session_id}/messages", status_code=201)
def teller_says(
    session_id: str,
    payload: SessionMessageIn,
    principal: Principal = NeedsTellerServe,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The teller typing to the customer.

    Stored under its own role — never `assistant`. Everything filed under the
    assistant's name is meant to have come from the bank's indexed content,
    and a human's typing under that role would be indistinguishable from it
    afterwards in the transcript, the analytics and any audit.

    Only the teller on the session, like every other action on a live call:
    someone reading the queue is not in this conversation.
    """
    bank = principal.bank
    session = _live_session(db, bank, session_id)
    if principal.user is None or session.teller_user_id != principal.user.id:
        raise HTTPException(
            status_code=403, detail="Only the teller on this session can write to it"
        )
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Empty message")
    db.add(
        Message(
            conversation_id=session.conversation_id, bank_id=bank.id,
            role=teller.MESSAGE_ROLE, text=text,
        )
    )
    db.commit()
    return _thread(db, session)[-1]


@app.delete("/chat/{slug}/teller-session/{session_id}")
def abandon_teller_session(
    slug: str, session_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """The customer left — gave up in the queue, hung up, or closed the tab.

    Both exits, because from the customer's side it is one action and the
    server has to be told either way. Which state it lands in is not:

    - waiting -> ABANDONED. Queue abandonment is the most useful number this
      feature produces and the one that justifies staffing.
    - on a call -> ENDED. The call happened; it simply finished without the
      teller writing a resolution.

    Reported from the field, and the reason this now accepts an active
    session at all: a customer hung up and the teller's screen stayed in the
    call, showing a live session with nobody on the other end. The widget
    disconnected from the media layer and told nobody, so the row stayed
    ACTIVE forever — it would still have been ACTIVE the next morning, in the
    teller's In-progress list, above the people actually waiting.

    The audit action distinguishes the two, so a bank can tell "the customer
    hung up" from "the teller wrapped up" without inferring it from a null
    resolution.
    """
    bank = _get_bank(db, slug)
    session = db.get(TellerSession, session_id)
    if session is None or session.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown session")
    # Idempotent: a hang-up and a closing tab both fire this, and the second
    # one must not be an error the customer's browser reports.
    if session.state in teller.TERMINAL:
        return {"state": session.state}
    on_a_call = session.state == teller.ACTIVE
    session.state = teller.move(
        session.state, teller.ENDED if on_a_call else teller.ABANDONED
    )
    session.ended_at = datetime.now(UTC)
    _audit(
        db, bank,
        "teller_session_customer_hung_up" if on_a_call
        else "teller_session_abandoned",
        "teller_session", session.id,
        {"waited_seconds": session.waited_seconds}, actor="customer",
    )
    db.commit()
    return {"state": session.state}


class TellerPresenceIn(BaseModel):
    on_duty: bool


@app.post("/admin/api/{slug}/teller/presence")
def set_teller_presence(
    payload: TellerPresenceIn,
    principal: Principal = NeedsTellerServe,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A teller declaring they are at a desk, and the heartbeat that keeps it true.

    The console calls this every `heartbeat_seconds` from the shell, on every
    page, so being available no longer depends on which screen happens to be
    open. That dependency is what produced the symptom this fixes: the feature
    was on, a teller was signed in, and the customer's Connect button never
    appeared because the teller was looking at Reports.

    `teller.serve` and self-only. Presence is a claim about where YOU are;
    nobody else can make it for you, and no supervisor can put a colleague on
    the air. The break-glass token has no user, so it cannot appear on the
    queue as a person a customer can be routed to.
    """
    if principal.user is None:
        raise HTTPException(
            status_code=403, detail="Sign in as a person to go on duty"
        )
    was = presence.on_duty(principal.user)
    presence.set_duty(principal.user, on_duty=payload.on_duty)
    # Audited only on the edges, not on every heartbeat — 2,880 rows a day per
    # teller would bury the events an auditor actually reads. Going on and off
    # the air is the event; still being there is not.
    if was != payload.on_duty:
        _audit(
            db, principal.bank,
            "teller_on_duty" if payload.on_duty else "teller_off_duty",
            "user", principal.user.id, {}, actor=principal.audit_actor,
        )
    db.commit()
    return {
        "on_duty": payload.on_duty,
        "heartbeat_seconds": presence.HEARTBEAT_SECONDS,
        # What the tenant looks like from a customer's side after this call.
        # A teller who goes on duty and still sees false learns immediately
        # that something else is wrong — the feature is off for the tenant, or
        # the media layer is unconfigured — instead of waiting for a call that
        # was never going to be offered.
        "available": presence.teller_available(db, principal.bank),
    }


class TellerLanguagesIn(BaseModel):
    languages: list[str] = Field(default_factory=list)


@app.put("/admin/api/{slug}/teller/languages")
def set_teller_languages(
    payload: TellerLanguagesIn,
    principal: Principal = NeedsTellerServe,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Which languages this teller can hold a conversation in. Their own.

    `teller.serve` and self-only — not `users.manage`. Whether you can talk to
    a customer in Afaan Oromoo is a fact about you, and the person who knows
    it is you. Routing a customer to a teller because a manager once ticked a
    box produces a call where neither party can proceed.

    An empty list clears it, which reads as "not declared" and routes
    everything to them — the same as a teller who never filled it in.
    """
    if principal.user is None:
        raise HTTPException(
            status_code=403, detail="Sign in as a person to set your languages"
        )
    unknown = [c for c in payload.languages if c not in SUPPORTED_LANGUAGES]
    if unknown:
        # Refused rather than quietly dropped. An ignored code would leave a
        # teller believing they are routed work they will never be offered.
        raise HTTPException(
            status_code=422, detail=f"Unsupported language: {', '.join(unknown)}"
        )
    # De-duplicated and in a stable order, so two tellers who picked the same
    # set store the same value.
    chosen = [c for c in SUPPORTED_LANGUAGES if c in set(payload.languages)]
    principal.user.teller_languages = chosen or None
    _audit(
        db, principal.bank, "teller_languages_updated", "user", principal.user.id,
        {"languages": chosen}, actor=principal.audit_actor,
    )
    db.commit()
    return {"languages": chosen}


class TellerSettingsIn(BaseModel):
    enabled: bool


@app.get("/admin/api/{slug}/teller/settings")
def get_teller_settings(
    principal: Principal = NeedsSessionsRead, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Whether this tenant offers live sessions, and whether anyone is on now.

    `available` is what the customer's widget is actually deciding on, so it is
    returned here too — a bank that has switched the feature on and sees
    "nobody watching" has the answer to why no button appeared, without anyone
    reading a log.
    """
    bank = principal.bank
    return {
        "enabled": bank.teller_enabled,
        "available": _teller_available(db, bank),
        "presence_window_seconds": int(TELLER_PRESENCE_WINDOW.total_seconds()),
        "heartbeat_seconds": presence.HEARTBEAT_SECONDS,
        # Whether THIS teller is on the air, as the server sees it. Read for
        # display, not to drive the toggle: the browser DECLARES duty and the
        # server records the declaration, so a console that reconciled its
        # switch against this would end up fighting its own heartbeat. It is
        # here so the Live queue strip can distinguish "somebody is available"
        # from "you are available".
        "on_duty": (
            principal.user is not None and presence.on_duty(principal.user)
        ),
        # This teller's own declared languages, so the page can show them
        # without a second request. Null for the break-glass token, which is
        # nobody in particular.
        "languages": (
            principal.user.teller_languages if principal.user is not None else None
        ),
        "all_languages": [
            {"code": c, "name": LANGUAGE_NAMES[c]} for c in SUPPORTED_LANGUAGES
        ],
    }


@app.put("/admin/api/{slug}/teller/settings")
def set_teller_settings(
    payload: TellerSettingsIn,
    principal: Principal = NeedsIntegrationsManage,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Turn live teller sessions on or off for this tenant.

    `integrations.manage` rather than `teller.serve`: this decides whether the
    bank offers the service at all, which is the same class of decision as
    repointing the handoff webhook. A teller answering calls should not be able
    to switch the product on for the whole tenant.

    Switching it off leaves sessions already in the queue alone. Those are real
    people waiting, and dropping them silently to make a toggle tidy is the
    kind of cleanup that loses a customer mid-conversation; the queue drains
    and no new sessions can start.
    """
    bank = principal.bank
    bank.teller_enabled = payload.enabled
    _audit(
        db, bank, "teller_settings_updated", "bank", bank.id,
        {"enabled": payload.enabled}, actor=principal.audit_actor,
    )
    db.commit()
    return {"enabled": bank.teller_enabled, "available": _teller_available(db, bank)}


@app.get("/admin/api/{slug}/teller/queue")
def teller_queue(
    principal: Principal = NeedsSessionsRead, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """Who is waiting, oldest first.

    Oldest first is not a preference — anything else means the person who has
    waited longest keeps losing, which is how a queue produces the abandonment
    it was built to prevent.
    """
    bank = principal.bank
    # Deliberately does NOT touch presence. Watching this page used to be the
    # presence signal, which had two failures pointing in opposite directions:
    # a teller working anywhere else in the console silently went off the air,
    # and a teller who had explicitly gone OFF duty was put back on by the
    # page's own poll. Duty is declared at /teller/presence and nowhere else.
    rows = db.execute(
        select(TellerSession)
        .where(
            TellerSession.bank_id == bank.id,
            TellerSession.state.in_((teller.QUEUED, teller.ACTIVE)),
        )
        .order_by(TellerSession.requested_at)
    ).scalars().all()
    out = [_session_admin(db, s) for s in rows]

    # Language routing, computed per teller rather than stored on the queue:
    # the same queue is a different order for an Amharic speaker than for an
    # Afaan Oromoo one, so there is no single correct order to persist.
    #
    # Only the waiting ones are reordered. An active session belongs to
    # whoever is already on it, and shuffling somebody else's live call around
    # the list is noise.
    mine = principal.user.teller_languages if principal.user is not None else None
    for row in out:
        row["speaks"] = teller.speaks(mine, row["language"])
    waiting = [i for i, r in enumerate(out) if r["state"] == teller.QUEUED]
    order = teller.queue_order(
        [(out[i]["language"], out[i]["waited_seconds"]) for i in waiting], mine
    )
    return (
        [out[waiting[j]] for j in order]
        + [r for r in out if r["state"] != teller.QUEUED]
    )


@app.post("/admin/api/{slug}/teller/sessions/{session_id}/claim")
def claim_teller_session(
    session_id: str,
    principal: Principal = NeedsTellerServe,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A teller taking the next customer.

    Requires `teller.serve`, which operators deliberately do not hold: working
    a queue after the fact and appearing live as the bank are different jobs.

    The state machine is what stops two tellers claiming the same person —
    `move()` raises on active -> active rather than quietly succeeding, which
    in a boolean world would look like both of them got it.
    """
    bank = principal.bank
    session = db.get(TellerSession, session_id)
    if session is None or session.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown session")
    if principal.user is None:
        # The break-glass admin token has no person behind it, and a live
        # customer call must be answerable to a named employee.
        raise HTTPException(
            status_code=403, detail="Sign in as a person to take a session"
        )
    try:
        session.state = teller.move(session.state, teller.ACTIVE)
    except teller.InvalidTransition:
        raise HTTPException(
            status_code=409, detail="That session is no longer waiting"
        ) from None
    session.teller_user_id = principal.user.id
    session.claimed_at = datetime.now(UTC)
    _audit(
        db, bank, "teller_session_claimed", "teller_session", session.id,
        {"waited_seconds": session.waited_seconds}, actor=principal.audit_actor,
    )
    db.commit()
    return _session_admin(db, session)


@app.post("/admin/api/{slug}/teller/sessions/{session_id}/verify")
def verify_teller_session(
    session_id: str,
    payload: SessionVerifyIn,
    principal: Principal = NeedsTellerServe,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The teller attests that this is the account holder.

    The bar is enforced in `verification.attest`, not here and not in the UI —
    a teller ticking a box having asked nothing is not verification, and a
    scheme that cannot tell the difference is decoration.
    """
    bank = principal.bank
    session = db.get(TellerSession, session_id)
    if session is None or session.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown session")
    if session.state != teller.ACTIVE:
        raise HTTPException(
            status_code=409, detail="Only a session you are in can be verified"
        )
    if principal.user is None or session.teller_user_id != principal.user.id:
        # Only the teller on the call. Someone reading the queue has not seen
        # the ID and has not asked anything — their attestation would be a
        # statement about something they did not witness.
        raise HTTPException(
            status_code=403, detail="Only the teller on this session can verify it"
        )
    try:
        attestation = verification.attest(
            checks=set(payload.checks),
            teller_user_id=principal.user.id,
            fayda_number=payload.fayda_number,
        )
    except verification.AttestationRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    session.scope = teller.VERIFIED
    session.verified_method = attestation.method
    session.verified_ref = attestation.reference
    session.verified_at = datetime.now(UTC)
    # WHAT was checked, not just that something was. A dispute needs to know
    # what the teller looked at, and `metadata` is the only place that
    # survives. The Fayda number is not here and never reaches the log.
    _audit(
        db, bank, "teller_session_verified", "teller_session", session.id,
        {"method": attestation.method, "checks": sorted(attestation.checks)},
        actor=principal.audit_actor,
    )
    db.commit()
    return _session_admin(db, session)


@app.post("/admin/api/{slug}/teller/sessions/{session_id}/end")
def end_teller_session(
    session_id: str,
    payload: SessionEndIn | None = None,
    principal: Principal = NeedsTellerServe,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Finish, with a note about what was done.

    The note is written to the session AND to the handoff it belongs to, when
    there is one — the session is the record of the encounter, the handoff is
    the record of the work, and a supervisor reading either should not have to
    open the other.
    """
    bank = principal.bank
    session = db.get(TellerSession, session_id)
    if session is None or session.bank_id != bank.id:
        raise HTTPException(status_code=404, detail="Unknown session")
    try:
        session.state = teller.move(session.state, teller.ENDED)
    except teller.InvalidTransition:
        raise HTTPException(status_code=409, detail="That session is not active") from None
    session.ended_at = datetime.now(UTC)
    if payload is not None and payload.resolution:
        session.resolution = payload.resolution.strip() or None
    if session.handoff_id and session.resolution:
        handoff = db.get(Handoff, session.handoff_id)
        if handoff is not None and handoff.bank_id == bank.id:
            handoff.resolution = session.resolution
            handoff.status = "closed"
            handoff.resolved_at = session.ended_at
            handoff.resolved_by = session.teller_user_id
    _audit(
        db, bank, "teller_session_ended", "teller_session", session.id,
        {"had_resolution": bool(session.resolution), "scope": session.scope},
        actor=principal.audit_actor,
    )
    db.commit()
    return _session_admin(db, session)
