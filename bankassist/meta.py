"""WhatsApp, Messenger and Instagram Direct — one Meta app, three products.

Written as a single module rather than three because that is what Meta
actually is: one app, one callback URL, one app secret, one signature scheme,
and one webhook envelope. Only the innermost payload and the send call differ.
Three copies of this file would be three places to fix the next time Meta
changes a version string, and two of them would be missed.

**The verification handshake.** Meta confirms an endpoint by GETting it with
`hub.mode=subscribe`, `hub.verify_token` and `hub.challenge`, and expects the
challenge echoed back as bare text. Get this wrong and the callback simply
cannot be registered — there is no partial success to debug from.

**The signature.** Inbound POSTs carry `X-Hub-Signature-256: sha256=<hex>`,
HMAC-SHA256 over the raw body keyed with the **app secret** — not the access
token, which is the mistake worth naming because both are long opaque strings
sitting next to each other in the dashboard.

**The envelope.** Every product delivers:

    {"object": "<product>", "entry": [{... , "messaging"|"changes": [...]}]}

`object` is what says which product a delivery belongs to, which is why one
route can serve all three. WhatsApp puts messages under `changes[].value`;
Messenger and Instagram share the older `messaging[]` shape.

**What is NOT solved here, and cannot be from code.** Meta requires a verified
business, a reviewed use case, and — for WhatsApp — approved templates for any
message sent first rather than in reply. This module is finished and tested;
switching a channel on is still gated on that review. The point of finishing
it anyway is that the day the review clears, the work is credential entry.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

# Pinned deliberately. Meta deprecates versions on a schedule, and an
# unpinned "latest" turns their calendar into our outage.
API_VERSION = "v21.0"
_GRAPH = f"https://graph.facebook.com/{API_VERSION}"

WHATSAPP = "whatsapp"
MESSENGER = "messenger"
INSTAGRAM = "instagram"

# `object` in the webhook envelope -> our channel name.
OBJECT_TO_CHANNEL = {
    "whatsapp_business_account": WHATSAPP,
    "page": MESSENGER,
    "instagram": INSTAGRAM,
}

# WhatsApp rejects a body over 4,096 characters; Messenger and Instagram cut
# off at 2,000. Truncating loses the tail of a long answer, which is visible
# and recoverable — a rejected send is silent and is not.
MAX_TEXT = {WHATSAPP: 4096, MESSENGER: 2000, INSTAGRAM: 2000}


def valid_signature(app_secret: str, body: bytes, header: str) -> bool:
    """Constant-time check of `X-Hub-Signature-256`.

    Fails closed on a missing secret or header. Without the empty check,
    HMAC with an empty key is still perfectly valid, so an unconfigured
    tenant would accept anything signed with "".
    """
    if not app_secret or not header:
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    # Meta prefixes the digest. Compare the whole thing so a header that omits
    # the prefix does not match a bare digest.
    return hmac.compare_digest(f"sha256={expected}", header)


def verify_handshake(
    *, mode: str, token: str, challenge: str, expected_token: str
) -> str | None:
    """The GET subscription handshake. Returns the challenge to echo, or None.

    Fails closed on an unset expected token, so a tenant that has not been
    configured cannot have its callback claimed by whoever guesses the slug.
    """
    if not expected_token or mode != "subscribe":
        return None
    if not hmac.compare_digest(token, expected_token):
        return None
    return challenge


# ------------------------------------------------------------------ inbound


def _texts_from_whatsapp(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """(sender, text) pairs from a WhatsApp Cloud API entry.

    Statuses (sent/delivered/read) arrive in this same envelope under
    `value.statuses` and carry no `messages` key — they must not be mistaken
    for someone talking.
    """
    out: list[tuple[str, str]] = []
    for change in entry.get("changes") or []:
        value = change.get("value") or {}
        for message in value.get("messages") or []:
            # Images, audio, location and button replies all appear here with
            # no `text`. There is nothing for the agent to read.
            body = (message.get("text") or {}).get("body")
            sender = message.get("from")
            if body and sender:
                out.append((str(sender), body))
    return out


def _texts_from_messaging(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """(sender, text) pairs from a Messenger or Instagram entry.

    `is_echo` marks a message the *page itself* sent — including the replies
    this service just sent. Treating one as inbound makes the assistant answer
    its own answer, which is an infinite loop that costs a model call each
    time round. It is the single most expensive mistake available here.
    """
    out: list[tuple[str, str]] = []
    for event in entry.get("messaging") or []:
        message = event.get("message") or {}
        if message.get("is_echo"):
            continue
        text = message.get("text")
        sender = (event.get("sender") or {}).get("id")
        if text and sender:
            out.append((str(sender), text))
    return out


def inbound(payload: dict[str, Any]) -> tuple[str | None, list[tuple[str, str]]]:
    """(channel, [(sender, text), ...]) for any Meta webhook body.

    Returns a null channel for an object we do not serve, so an app
    subscribed to extra products cannot drive traffic into the wrong one.
    """
    channel = OBJECT_TO_CHANNEL.get(str(payload.get("object")))
    if channel is None:
        return None, []
    reader = _texts_from_whatsapp if channel == WHATSAPP else _texts_from_messaging
    found: list[tuple[str, str]] = []
    for entry in payload.get("entry") or []:
        found.extend(reader(entry))
    return channel, found


# ----------------------------------------------------------------- outbound


def _post(url: str, token: str, body: dict[str, Any]) -> bool:
    """Send, log failures, never raise.

    Raising would 500 the webhook, and Meta responds to repeated non-2xx by
    retrying and eventually disabling the subscription — so one bad token
    could silently switch the channel off.
    """
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=get_settings().request_timeout,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("meta send failed (%s): %s", url, exc)
        return False


def send_whatsapp(access_token: str, phone_number_id: str, to: str, text: str) -> bool:
    return _post(
        f"{_GRAPH}/{phone_number_id}/messages",
        access_token,
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text[: MAX_TEXT[WHATSAPP]]},
        },
    )


def send_messaging(access_token: str, to: str, text: str, *, channel: str) -> bool:
    """Messenger and Instagram share one send endpoint and one body shape.

    `messaging_type: RESPONSE` declares this as a reply to a user-initiated
    message. It is what keeps the send inside the standard messaging window
    without a paid template — correct here because this product only ever
    replies, and never messages a customer first.
    """
    return _post(
        f"{_GRAPH}/me/messages",
        access_token,
        {
            "recipient": {"id": to},
            "messaging_type": "RESPONSE",
            "message": {"text": text[: MAX_TEXT.get(channel, 2000)]},
        },
    )
