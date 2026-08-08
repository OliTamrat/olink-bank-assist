from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def new_token() -> str:
    return secrets.token_urlsafe(24)


class Bank(Base):
    """A tenant. Every row of tenant data carries bank_id — never query without it."""

    __tablename__ = "banks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    primary_color: Mapped[str] = mapped_column(String(16), default="#0f766e")
    # Optional tenant logo, rendered in the widget header in place of the
    # name's initials. A brand colour alone leaves tenants looking like the
    # same product with a different tint — the logo is what makes a bank
    # recognise a demo as theirs. Nullable; initials stay the fallback.
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_language: Mapped[str] = mapped_column(String(8), default="en")
    admin_token: Mapped[str] = mapped_column(String(64), default=new_token)
    # Shown as a banner in the widget. Used for pre-contract sales demos built
    # from a prospect's public info, so the prototype is never mistaken for
    # that institution's own official channel. Null for a bank's live tenant.
    disclaimer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Whether the assistant may answer universally-standard banking questions
    # (how to use an ATM, what a PIN is) from general knowledge when the bank's
    # own knowledge base has nothing. Bounded exception to tool-output-is-truth:
    # the model is forbidden from stating any figure, fee, limit, requirement or
    # anything specific to this bank, and the reply is labelled as general
    # guidance rather than the bank's official information. Per-tenant because a
    # compliance-conservative bank will want it off.
    allow_general_knowledge: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_bot_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    telegram_webhook_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Where to POST a handoff so it lands in the bank's own contact-centre tool
    # rather than only in our console. Null = off, and that has to stay the
    # default: the payload carries a customer's question and their phone
    # number, which is personal data leaving our control.
    handoff_webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Shared secret for the HMAC signature on each POST. Without it the
    # receiving system cannot tell our request from anyone else's who learns
    # the URL.
    handoff_webhook_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    documents: Mapped[list[Document]] = relationship(back_populates="bank")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bank_id: Mapped[str] = mapped_column(ForeignKey("banks.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(64), default="general")
    language: Mapped[str] = mapped_column(String(8), default="en")
    content: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    bank: Mapped[Bank] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bank_id: Mapped[str] = mapped_column(String(36), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bank_id: Mapped[str] = mapped_column(String(36), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="web")  # web | telegram
    external_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # A name the customer volunteered ("I'm Oli"), used to address them for
    # the rest of the conversation. Personal data: never written to logs
    # (log_event carries metadata only) and only ever set from an explicit
    # self-introduction — see classifier.extract_name.
    customer_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # A phone number or email the customer gave so a person could call them
    # back about a handoff. Personal data, exactly like customer_name: never
    # logged, only ever set from a message sent in reply to an explicit ask.
    # Held on the conversation so a second handoff in the same chat inherits
    # it — being asked for your number twice reads as nobody being on the
    # other end.
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # True between asking for contact details and getting (or giving up on)
    # them. One turn only: if the customer replies with something that isn't
    # contact details, the flag clears and the message is answered normally.
    # Nagging a customer who changed the subject is worse than missing a
    # phone number.
    awaiting_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    bank_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # What the assistant actually did on this turn — see agent.Outcome. Set on
    # assistant messages only; null on the customer's own messages, and on any
    # assistant message written before migration 0007. Analytics reports those
    # as unclassified rather than guessing, because a bank is being asked to
    # trust these numbers.
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Handoff(Base):
    __tablename__ = "handoffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bank_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    # Snapshot of how to reach this customer, so an operator working the queue
    # sees who to call on the row itself. Copied from the conversation when the
    # handoff is filed, and backfilled onto still-open handoffs if the details
    # arrive afterwards — which is the normal order, since we only ask once a
    # handoff exists.
    contact_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | closed
    # What the operator did about it. Free text on purpose: a fixed set of
    # codes would have to be guessed before a single bank has worked the
    # queue, and the wrong vocabulary is harder to remove later than none.
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Nullable, and it will stay nullable. Every handoff resolved before
    # per-person logins existed has no person to name, and one resolved through
    # the break-glass token still has none — a tenant-wide token is not
    # somebody. Writing "admin" into those rows would turn "we do not know"
    # into a specific false claim, which is the one thing an audit trail must
    # never do. Null means exactly what it says; audit_log.actor carries
    # "admin-token" for the break-glass case.
    resolved_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_id: Mapped[str] = mapped_column(String(36), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))  # TEXT on purpose — always str(uuid)
    log_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --------------------------------------------------------------- admin identity
#
# Who someone is (User) is kept apart from how they prove it (UserCredential).
# That split is what lets SSO arrive later as another credential row rather
# than a rewrite of everything touching a user, and what lets one person hold
# a password and a TOTP secret without a nullable column per method.


class Role(Base):
    """A named bundle of permissions, owned by one bank.

    Per-bank rather than global, including the two built-ins, which are seeded
    once per tenant. Three reasons, in order of weight:

    1. A bank can reshape its own org structure — rename a role, take
       `documents.write` off it — without that reaching another bank. Shared
       rows would make one tenant's edit everyone's.
    2. Every query stays bank-scoped, which is the multi-tenancy rule this
       codebase applies everywhere else. Global roles would mean
       `bank_id == x OR bank_id IS NULL` at each lookup, and the day someone
       forgets the OR is the day a role goes missing — or worse, the day they
       write it as `bank_id != x` by accident.
    3. `UNIQUE(bank_id, name)` actually holds. With a nullable `bank_id`,
       Postgres treats NULLs as distinct, so the constraint would silently
       permit two system roles both called `admin` — a uniqueness guarantee
       that is not one.

    The cost is duplicated rows per tenant and a seeding step. That is cheap
    and boring, which is what this should be.
    """

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("bank_id", "name", name="uq_roles_bank_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bank_id: Mapped[str] = mapped_column(ForeignKey("banks.id"), index=True)
    name: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Marks the two roles seeded for every tenant. They can be edited — a bank
    # narrowing its own `operator` is the point — but not deleted, so a tenant
    # cannot remove the only role that holds users.manage and lock itself out.
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RolePermission(Base):
    """One permission granted to one role.

    A row per grant rather than a JSON list on `roles`, so "which roles can
    repoint the handoff webhook" is a one-line query instead of a scan that
    parses every blob — the question an access review actually asks.
    """

    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id"), primary_key=True, index=True
    )
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)


class User(Base):
    """A person with access to one tenant's admin panel."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("bank_id", "email", name="uq_users_bank_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bank_id: Mapped[str] = mapped_column(ForeignKey("banks.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The role's id, not its name. A bank renaming "operator" must not silently
    # drop everyone holding it back to no permissions, which is exactly what a
    # name-matched lookup would do.
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), index=True)
    # Disabled rather than deleted, so an audit entry naming this id still
    # resolves after the person has left the bank.
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @property
    def is_active(self) -> bool:
        return self.disabled_at is None


class UserCredential(Base):
    """How a user proves who they are. One row per method."""

    __tablename__ = "user_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_credentials_user_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # password | totp | oidc — a string rather than an enum, so adding a
    # method later is not a migration in every environment.
    kind: Mapped[str] = mapped_column(String(16))
    secret_hash: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AdminSession(Base):
    """A logged-in browser. Server-side so it can be revoked.

    Named AdminSession rather than Session because this module is read
    alongside sqlalchemy.orm.Session everywhere, and one of those two being
    silently the wrong one is a bug nobody would enjoy finding.
    """

    __tablename__ = "admin_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # The hash, never the token itself — a database read must not yield a
    # working credential, the same rule the password column follows.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Recorded so a person can be shown their own sessions and recognise one
    # they did not start. Not used for authorization: both are client-supplied
    # and trivially forged.
    created_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
