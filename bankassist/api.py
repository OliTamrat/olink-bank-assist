from __future__ import annotations

import hmac
import logging
import time
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
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from . import (
    admin_auth,
    channels,
    handoff_webhook,
    passwords,
    permissions,
    roles,
    telegram,
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
    Handoff,
    Message,
    Role,
    User,
    UserCredential,
    new_token,
)
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


@app.get("/banks/{slug}/public")
def bank_public(slug: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    bank = _get_bank(db, slug)
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


class TelegramConnectIn(BaseModel):
    bot_token: str = Field(min_length=10)


@app.post("/admin/api/{slug}/telegram/connect")
def telegram_connect(
    slug: str, payload: TelegramConnectIn,
    principal: Principal = NeedsIntegrationsManage, db: Session = Depends(get_db),
) -> dict[str, Any]:
    bank = principal.bank
    bank.telegram_bot_token = payload.bot_token
    bank.telegram_webhook_secret = new_token()
    webhook_url = f"{get_settings().app_base_url}/webhooks/telegram/{bank.slug}"
    response = telegram.set_webhook(payload.bot_token, webhook_url, bank.telegram_webhook_secret)
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
        admin_auth.revoke(db, token)
        db.commit()
    response.delete_cookie(admin_auth.COOKIE_NAME, path="/admin")
    return {"signed_out": True}


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
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": u.created_at.isoformat(),
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
            "language": d.language, "updated_at": d.updated_at.isoformat(),
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
    return [
        {
            "id": c.id, "channel": c.channel, "language": c.language,
            "created_at": c.created_at.isoformat(),
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
            "sources": m.sources, "created_at": m.created_at.isoformat(),
        }
        for m in msgs
    ]


@app.get("/admin/api/{slug}/handoffs")
def list_handoffs(
    status: str = "open",
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
    order = Handoff.created_at.asc() if status == "open" else Handoff.created_at.desc()

    rows = db.execute(query.order_by(order).limit(200)).scalars().all()
    return [
        {
            "id": h.id, "reason": h.reason, "detail": h.detail, "status": h.status,
            "conversation_id": h.conversation_id, "created_at": h.created_at.isoformat(),
            # Who to call. The whole point of a handoff queue is that someone
            # works it, and until now a row said a customer wanted a callback
            # without saying where to.
            "contact_name": h.contact_name, "contact_phone": h.contact_phone,
            "resolution": h.resolution,
            "resolved_at": h.resolved_at.isoformat() if h.resolved_at else None,
        }
        for h in rows
    ]


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
        # Every channel, with what each actually requires. Served rather than
        # written into the page so the answer to "can you do WhatsApp" is one
        # list, kept next to the code that would implement it.
        "channels": channels.catalogue(
            telegram_connected=bool(bank.telegram_bot_token)
        ),
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
            "at": r.created_at.isoformat(),
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
                "at": r.created_at.isoformat(),
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
                "last_asked": h.created_at.isoformat(),
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
    catalogue = channels.catalogue(
        telegram_connected=bool(bank.telegram_bot_token)
    )
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
        "since": since.isoformat() if since else None,
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
