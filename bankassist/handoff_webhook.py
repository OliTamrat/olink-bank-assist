"""Deliver a handoff into the bank's own contact-centre tool.

The admin console is one way to work the queue. A bank already running
Freshdesk, Zendesk or an in-house CRM will not adopt a second inbox for a
pilot, and asking them to is how a pilot stalls on a process question rather
than on the product.

Three rules, and each one is load-bearing.

**Failure never reaches the customer.** The delivery happens after the reply
is composed and is wrapped so that a timeout, a DNS failure or a 500 from the
bank's own tooling cannot turn into a failed chat turn. A customer reporting
theft must get their acknowledgement whether or not the bank's CRM is up. The
handoff is already committed to our database by then, so a dropped webhook
loses a notification, never the record.

**Every request is signed.** A URL is not a secret — it ends up in runbooks,
in tickets, in a screenshot. The receiving system needs to be able to prove a
POST came from us, so each body is signed HMAC-SHA256 with the tenant's own
secret and the signature travels in `X-Bankassist-Signature`.

**The payload is the minimum that makes it actionable.** An operator needs to
know who to call, about what, and where to find the rest. It carries no
transcript: the conversation may contain things the customer said before they
knew a person would read it, and this is the one path where our data leaves
our control.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from .config import get_settings
from .models import Bank, Handoff

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Bankassist-Signature"
EVENT_HEADER = "X-Bankassist-Event"


def sign(secret: str, body: bytes) -> str:
    """`sha256=<hex>`, the shape GitHub and Stripe both use.

    Naming the algorithm in the value is what lets it be changed later without
    the receiving end having to guess which one was used.
    """
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_payload(bank: Bank, handoff: Handoff) -> dict[str, Any]:
    """What an operator needs to act, and nothing more.

    Deliberately excludes the conversation transcript. A customer says things
    to a machine they would not put in a ticket, and this is the one path
    where the data leaves our control — the console can show the transcript to
    someone already inside it, under this bank's own access rules.
    """
    return {
        "event": "handoff.created",
        "bank": bank.slug,
        "handoff_id": str(handoff.id),
        "conversation_id": str(handoff.conversation_id),
        "reason": handoff.reason,
        "question": handoff.detail,
        "contact_name": handoff.contact_name,
        "contact_phone": handoff.contact_phone,
        "created_at": handoff.created_at.isoformat() if handoff.created_at else None,
    }


def deliver(bank: Bank, handoff: Handoff) -> bool:
    """POST the handoff. Returns whether it was delivered.

    Never raises. A bank's CRM being down, slow or misconfigured is not the
    customer's problem, and the handoff row is already committed — so the
    worst case here is a missed notification that the console still shows.
    """
    url = bank.handoff_webhook_url
    secret = bank.handoff_webhook_secret
    if not url:
        return False
    if not secret:
        # Refuse rather than send unsigned. An unsigned POST is one the
        # receiving system cannot authenticate, so a half-configured tenant
        # would be shipping a customer's phone number to an endpoint that
        # cannot tell whether it really came from us.
        logger.warning(
            "handoff webhook not sent: url configured without a secret",
            extra={"bank": bank.slug},
        )
        return False

    body = json.dumps(build_payload(bank, handoff), ensure_ascii=False).encode()
    try:
        resp = httpx.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                EVENT_HEADER: "handoff.created",
                SIGNATURE_HEADER: sign(secret, body),
            },
            timeout=get_settings().request_timeout,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        # The URL is logged; the payload never is. It carries the customer's
        # question and phone number, and logs are the easiest place for
        # personal data to end up somewhere nobody is auditing.
        logger.warning(
            "handoff webhook failed: %s", exc,
            extra={"bank": bank.slug, "handoff_id": str(handoff.id)},
        )
        return False
