"""SMS, through whichever aggregator the bank has an agreement with.

Every other channel here talks to one company's API. SMS does not: it goes
through an aggregator, and in Ethiopia that means Ethio Telecom or a reseller
in front of them. There is no single endpoint to hard-code, and pretending
otherwise would produce a module that works for exactly one contract.

So this defines **a contract instead of an integration**, and the bank's
gateway is configured against it:

*Inbound* — the aggregator POSTs to `/webhooks/sms/{slug}` with a shared
secret in `X-SMS-Secret`, and either form-encoded or JSON fields. Field names
vary by vendor, so several common spellings are accepted (`from`/`msisdn`/
`sender`, `text`/`message`/`body`). This is deliberately generous on the way
in and strict on authentication.

*Outbound* — a POST to `sms_send_url` with `sms_auth_header` sent verbatim as
the `Authorization` header, and a JSON body of `{to, text, from}`.

**Read this before assuming SMS is done.** The transport is finished and
tested; a specific aggregator whose body shape differs from the above needs a
mapping written for it, and that mapping cannot be written from guesswork —
it needs the vendor's spec. What is genuinely complete is everything around
it: authentication, the conversation model, the agent path, the disclaimer,
and segmentation.

**SMS is also the only channel that costs money per reply**, which changes one
design decision: a long answer is split into numbered parts rather than
truncated, but only up to `MAX_PARTS`, because an agent answer that runs long
would otherwise quietly bill the bank for a dozen messages to one customer.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

# A GSM-7 message is 160 characters, or 153 per part once concatenated. Using
# 153 keeps a split message billing as the parts we actually intend.
PART_CHARS = 153

# The ceiling on one answer. Four parts is roughly a paragraph; beyond that
# the right answer is "call us", not a wall of text the bank pays for by the
# segment.
MAX_PARTS = 4

# Vendors disagree about field names. Accepted spellings, in preference order.
_FROM_KEYS = ("from", "msisdn", "sender", "source", "originator")
_TEXT_KEYS = ("text", "message", "body", "content", "sms")


def parse_inbound(fields: dict[str, Any]) -> tuple[str | None, str | None]:
    """(sender, text) from an aggregator's callback, whatever it calls them."""
    sender = next(
        (str(fields[k]).strip() for k in _FROM_KEYS if fields.get(k)), None
    )
    text = next(
        (str(fields[k]).strip() for k in _TEXT_KEYS if fields.get(k)), None
    )
    return (sender or None), (text or None)


def segments(text: str) -> list[str]:
    """Split a reply into billable parts, numbered so they can be reassembled.

    Numbering matters because SMS parts can arrive out of order, and an
    unlabelled second half of an answer about a fee is worse than no answer.
    Single-part replies are never numbered — most replies are one part, and
    "(1/1)" on every message would look broken.
    """
    if len(text) <= PART_CHARS:
        return [text]

    # Reserve room for the " (n/m)" suffix that numbering adds.
    body = PART_CHARS - 6
    raw = [text[i : i + body] for i in range(0, len(text), body)]
    if len(raw) > MAX_PARTS:
        raw = raw[:MAX_PARTS]
        # Say it was cut. A silently truncated answer reads as a complete one.
        raw[-1] = raw[-1][: body - 1] + "…"
    total = len(raw)
    return [f"{part} ({i}/{total})" for i, part in enumerate(raw, start=1)]


def send_message(
    *, send_url: str, auth_header: str, to: str, text: str, sender_id: str
) -> bool:
    """Send a reply, one request per segment. Failures logged, never raised.

    Stops at the first failed segment rather than sending the rest: if part
    one did not arrive, parts two and three are noise the bank pays for.
    """
    if not send_url:
        logger.warning("sms send skipped: no gateway configured")
        return False

    headers = {"Content-Type": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header

    for part in segments(text):
        try:
            resp = httpx.post(
                send_url,
                headers=headers,
                json={"to": to, "text": part, "from": sender_id},
                timeout=get_settings().request_timeout,
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("sms send failed: %s", exc)
            return False
    return True
