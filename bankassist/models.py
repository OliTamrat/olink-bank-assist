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


def _utc(value: datetime) -> datetime:
    """A timezone-aware UTC datetime, whichever database it came from.

    Postgres returns aware values from a `DateTime(timezone=True)` column;
    SQLite returns naive ones, having no timezone type. Everything this
    project writes is UTC, so a naive value is a UTC value that lost its
    label — attaching it back is a correction, not an assumption.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def new_token() -> str:
    return secrets.token_urlsafe(24)


class Bank(Base):
    """A tenant. Every row of tenant data carries bank_id — never query without it."""

    __tablename__ = "banks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # The registered name, e.g. "Commercial Bank of Ethiopia". Kept separate
    # from what the bank is actually called because both are needed and they
    # are needed in different places.
    name: Mapped[str] = mapped_column(String(200))
    # What customers and staff call it — "CBE". Nullable; the full name is the
    # fallback, so a bank with no distinct short form needs nothing set.
    #
    # This exists because a straight rename would have been wrong in both
    # directions. "Commercial Bank of Ethiopia" in a chat header and a sidebar
    # is nobody's name for it and does not fit either. "CBE" on a printed
    # report in a board pack, or inside the model prompt, loses the registered
    # name at exactly the moment precision matters.
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_color: Mapped[str] = mapped_column(String(16), default="#0f766e")

    @property
    def display_name(self) -> str:
        """What to put in front of a person. Brand first, registered name if none."""
        return self.short_name or self.name
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
    # Whether this tenant offers live sessions with a human teller.
    #
    # Defaults OFF, unlike the flag above. The feature needs a named person
    # sitting on the queue page; a bank that has bought the assistant but has
    # not staffed a teller must not grow a "Talk to a teller" button in its
    # widget the day we deploy. Enabling it is a decision someone makes, not a
    # side effect of upgrading.
    teller_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_bot_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    telegram_webhook_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # No matching viber_webhook_secret: Viber signs the body with this same
    # token rather than echoing a secret we chose, so there is no second
    # credential to store. See migration 0024.
    viber_auth_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
    # Where this came from, when it was imported rather than typed. Provenance
    # for a compliance reviewer, and the key that lets a re-import replace what
    # it wrote last time instead of leaving the old fee beside the new one.
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    bank: Mapped[Bank] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Faq(Base):
    """A question a bank has answered in its own words, and approved.

    Separate from `Document` on purpose, though both hold text a customer ends
    up reading. A document is material the assistant may draw on; an FAQ is an
    answer the bank has committed to word for word, served verbatim with no
    model in the path. Storing them in one table would make "may we quote this
    exactly" a per-row flag on the thing everything else already reads — one
    bad query away from serving an unreviewed article as an approved answer.
    """

    __tablename__ = "faqs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bank_id: Mapped[str] = mapped_column(ForeignKey("banks.id"), index=True)
    # As a customer would type it. Kept verbatim for the admin to read; the
    # lookup key is the normalised form below.
    question: Mapped[str] = mapped_column(String(400))
    # The normalised (language, question) key. Unique per bank, so publishing
    # the same question twice is a database error rather than two answers and
    # a race to decide which one a customer sees.
    lookup: Mapped[str] = mapped_column(String(420), index=True)
    answer: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    # draft | published. Only published answers are ever served: an answer
    # half-written at 16:55 must not be what a customer reads at 16:56.
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # Who committed the bank to these words, and when. This is the whole
    # difference between a curated answer and a cached one — an approval with
    # nobody's name on it is a cache with extra steps.
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The answer this one was translated from, when it was. Lets the review
    # sheet put a question and its four translations on one row, and lets a
    # repeat translation batch tell "already covered" from "not yet" without
    # relying on the lookup key — which changes the moment a reviewer corrects
    # the wording of the translated question.
    source_faq_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    # How often it has actually been served. The number that tells a bank
    # whether curating more of these is worth anybody's afternoon.
    served: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        UniqueConstraint("bank_id", "lookup", name="uq_faq_bank_lookup"),
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
    channel: Mapped[str] = mapped_column(String(16), default="web")  # web | telegram | viber
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
    # Which desk answers this, and whether it can wait. See `departments.py`
    # for why these are two separate facts from `reason` — that one says why
    # the assistant let go, these say who picks it up and in what order.
    department: Mapped[str] = mapped_column(
        String(32), default="general", server_default="general"
    )
    priority: Mapped[str] = mapped_column(
        String(16), default="normal", server_default="normal"
    )
    # Whether a person is actually expected to do something about this.
    #
    # Not every row here is a customer waiting for a callback. When the
    # assistant answers from general banking knowledge it files a row so the
    # bank can see there is no content of its own on the subject — a real and
    # useful signal — but the customer got a complete answer and went away.
    # Those rows sat in the escalation queue as "open, no contact details",
    # which told an operator that nine people were waiting when nobody was.
    #
    # The queue and the "waiting for someone" count filter on this. Content
    # Gaps deliberately does not: for that report the row is the whole point.
    needs_person: Mapped[bool] = mapped_column(Boolean, default=True)
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
    # Last time this person was watching the teller queue. Touched by the queue
    # poll, which is the only honest evidence we have that somebody is actually
    # there — a login hours ago is not.
    #
    # This is what decides whether a customer is shown a "Talk to a teller"
    # button at all. Without it the button is a trap: tapped at 22:00 it queues
    # someone behind nobody, and the wait counter climbing with no one coming is
    # a worse answer than the assistant saying plainly that it cannot help.
    teller_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Which languages this person can actually hold a conversation in, as a
    # list of codes from i18n.SUPPORTED_LANGUAGES.
    #
    # EMPTY MEANS "NOT DECLARED", AND IS TREATED AS "CAN TAKE ANYTHING" — not
    # as "speaks nothing". Every teller starts empty, so failing closed would
    # empty every queue on the day this ships and make the feature look like
    # an outage. Declaring languages narrows what is routed to you first; it
    # never takes work away from a bank that has not filled it in.
    teller_languages: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
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


class TellerSession(Base):
    """A customer asking to speak to a person, and what happened next.

    Distinct from `Handoff` rather than a column on it, because the two answer
    different questions. A handoff is a piece of work in a queue — durable,
    async, closed at some point by somebody. A session is a live encounter with
    a clock on it: it can be abandoned while nobody is looking, it holds a
    media channel open, and its most valuable field is the one nobody has to
    act on (how long the customer waited before giving up).

    Both exist for the same conversation, and the session points at the
    handoff so a teller's resolution lands in the queue everyone already reads.

    See `docs/video-teller.md`.
    """

    __tablename__ = "teller_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bank_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    # Set once a teller claims it, so the resolution they write has somewhere
    # to go. Null while queued: a session may be abandoned before any work
    # exists to file.
    handoff_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # One of teller.STATES. A plain string rather than an enum for the same
    # reason the permission strings are: it is what a bank's own reporting
    # will group by, so the wire format is the thing that matters.
    state: Mapped[str] = mapped_column(String(16), default="requested", index=True)
    # One of teller.SCOPES. Decides what the teller may do — see teller.allows.
    scope: Mapped[str] = mapped_column(String(16), default="unverified")

    # How the customer was identified, and against what. Deliberately NOT the
    # identity document itself: we store that a check passed and its reference,
    # never the underlying record. Holding a copy of a national ID would make
    # this table the most sensitive thing in the product for no gain — the
    # bank's own system is the system of record.
    verified_method: Mapped[str | None] = mapped_column(String(24), nullable=True)
    verified_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # The teller who claimed it. A user id, so a session survives someone
    # leaving the bank — the audit row still resolves.
    teller_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # The media channel, when one exists. The NAME only: tokens are minted per
    # join, short-lived, and never stored. A durable token in a database row
    # is a durable way into a customer's banking call.
    channel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # audio | video. Recorded because it is the number that decides whether
    # video is worth what it costs, and nobody can reconstruct it afterwards.
    media: Mapped[str] = mapped_column(String(8), default="audio")

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    # Nullable and separate rather than one "closed_at": the gap between them
    # IS the queue wait, which is the single most useful number this feature
    # produces and the one that justifies staffing.
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # What the teller concluded. Mirrors Handoff.resolution deliberately — the
    # session is the record of the encounter, the handoff is the record of the
    # work, and a supervisor reading either should not have to open the other.
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def waited_seconds(self) -> int:
        """How long this customer has been waiting, or waited in the end.

        Counts to the claim for a session a teller took, to the end for one
        that was abandoned, and TO NOW for one still in the queue.

        That last case is the whole point and the first version of this got it
        wrong by returning None while waiting — which is precisely when the
        number matters. It rendered a queue where every waiting row showed a
        blank where the wait should be, and the wait is the only thing that
        tells a teller which customer to take next. A queue sorted oldest-first
        with no visible ages is a list.

        Both ends are coerced to UTC-aware before subtracting, because the two
        databases disagree: Postgres returns timezone-aware values from a
        `DateTime(timezone=True)` column and SQLite returns naive ones, having
        no timezone type to store. Subtracting one from the other raises. That
        makes this the worst shape of bug — it works in production and fails
        in tests, so the natural reading is "the test is wrong" and the
        natural fix is to weaken the test.
        """
        end = self.claimed_at or self.ended_at or _now()
        return max(0, int((_utc(end) - _utc(self.requested_at)).total_seconds()))
