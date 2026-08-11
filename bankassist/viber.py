"""Viber Channels API integration (plain REST via httpx).

The same shape as `telegram.py` — an outbound send and a webhook
registration — but three of Viber's differences are load-bearing and each one
is a silent failure if missed.

**1. A Viber error arrives as HTTP 200.** Every call returns 200 and reports
success in a JSON `status` field, where 0 is OK. `raise_for_status()` alone
therefore reports a send as successful when the token was rejected, the
account was not set live, or the user had unsubscribed. `_ok()` checks the
body, so a wrong token surfaces as a logged failure instead of silence.

**2. The signature key is the auth token itself.** Viber signs the raw request
body with HMAC-SHA256 using the same token used to send, and puts the hex
digest in `X-Viber-Content-Signature`. There is no separate webhook secret to
choose, which is why the bank row stores one credential and not two.

**3. `sender` is required on every message.** Telegram infers the bot from the
token; Viber wants a display name in each payload, and a send with no sender
is rejected — as a 200, per (1).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

_API = "https://chatapi.viber.com/pa"

# Viber pushes delivery receipts and read receipts as webhook events. Asking
# for only what is acted on keeps the endpoint from being woken twice per
# message for things it discards. "webhook" is Viber's own validation ping and
# is always delivered whether or not it is requested.
EVENT_TYPES = ["message", "subscribed", "unsubscribed", "conversation_started"]

# Viber rejects a text message over 7,000 characters. Nothing this product
# generates approaches that — a curated answer is a paragraph — but a
# retrieval answer over a long document could, and the failure would be a
# silent 200 with a non-zero status. Truncating is the lesser harm: a clipped
# answer is visibly clipped, whereas a dropped one looks like the bot ignored
# the customer.
MAX_TEXT = 7000


def _ok(resp: httpx.Response) -> bool:
    """True only if Viber reported success in the body, not merely HTTP 200."""
    try:
        body: dict[str, Any] = resp.json()
    except ValueError:
        logger.warning("viber returned non-JSON: %s", resp.text[:200])
        return False
    if body.get("status") != 0:
        logger.warning(
            "viber call failed: status=%s %s",
            body.get("status"),
            body.get("status_message"),
        )
        return False
    return True


def signature(auth_token: str, body: bytes) -> str:
    """The `X-Viber-Content-Signature` Viber should have sent for this body."""
    return hmac.new(auth_token.encode(), body, hashlib.sha256).hexdigest()


def valid_signature(auth_token: str, body: bytes, header: str) -> bool:
    """Constant-time check of an inbound webhook.

    Fails closed on a missing token: an unconfigured bank must not accept
    unsigned traffic, and `hmac.new(b"", ...)` would otherwise produce a
    perfectly checkable signature for anyone who guessed the empty key.
    """
    if not auth_token or not header:
        return False
    return hmac.compare_digest(signature(auth_token, body), header)


def send_message(auth_token: str, receiver: str, text: str, sender_name: str) -> bool:
    """Send a reply. Failures are logged, never raised.

    Same contract as the Telegram adapter and for the same reason: raising
    here would 500 the webhook, and Viber responds to a non-2xx by retrying
    the delivery — turning one failed send into a loop that re-runs the agent
    on every retry.
    """
    try:
        resp = httpx.post(
            f"{_API}/send_message",
            headers={"X-Viber-Auth-Token": auth_token},
            json={
                "receiver": receiver,
                "type": "text",
                "text": text[:MAX_TEXT],
                "sender": {"name": sender_name[:28]},
            },
            timeout=get_settings().request_timeout,
        )
        resp.raise_for_status()
        return _ok(resp)
    except Exception as exc:  # noqa: BLE001
        logger.warning("viber send_message failed: %s", exc)
        return False


def set_webhook(auth_token: str, url: str) -> dict[str, Any]:
    """Register this service as the account's webhook (used by the admin API).

    Unlike the send path this DOES raise, because it runs inside an operator's
    "Connect" click: a token that does not work has to be reported to the
    person pasting it, not logged where nobody looks.

    Viber validates by immediately POSTing a `webhook` event to the URL and
    will refuse registration if that call does not return 200 — so the route
    must answer this event before it is configured to expect it.
    """
    resp = httpx.post(
        f"{_API}/set_webhook",
        headers={"X-Viber-Auth-Token": auth_token},
        json={"url": url, "event_types": EVENT_TYPES},
        timeout=get_settings().request_timeout,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    if data.get("status") != 0:
        raise ValueError(
            f"Viber rejected the webhook: {data.get('status_message', 'unknown error')}"
        )
    return data
