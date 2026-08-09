"""LiveKit access tokens, and the room a teller session maps to.

Pure functions over strings and clocks — no network, no database. The service
is the media layer for tier-3 sessions (`docs/video-teller.md`); this file is
only the part that decides *who may join which room, for how long, and with
what permission*, which is the part worth testing exhaustively.

**Why the JWT is hand-rolled rather than pulled from a library.** We only ever
SIGN. LiveKit's server verifies. Signing HS256 is a base64url of two JSON
objects and one HMAC — the whole implementation is `_sign` below — whereas
*verifying* is where the dangerous subtleties live (algorithm confusion, `none`
acceptance, key-type mixups), and we do none of it. Adding a JWT dependency
would buy us the half of the problem we do not have.

**Rooms are named from the session id and nothing else.** A room name derived
from a bank slug or a customer's conversation id would be guessable by anyone
who has seen one, and a guessable room name plus a self-minted token is how a
stranger joins someone's banking call. Session ids are UUID4.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# How long a join token is good for. Short: the token is handed to a browser
# and its only job is to get through the door once. A session that runs longer
# than this is unaffected — LiveKit checks the token at join, not continuously.
#
# Ten minutes rather than one, because a customer who is granted a token while
# still in the queue may sit for several minutes before a teller takes them,
# and a token that expires in the waiting room turns a normal wait into a
# failed call.
TOKEN_TTL = timedelta(minutes=10)

# Tolerance for a customer's device clock running fast. Phones in the field are
# not NTP-synced; without this a device a minute ahead rejects its own token as
# not-yet-valid, and the failure looks like a server fault.
CLOCK_SKEW = timedelta(minutes=2)

ROOM_PREFIX = "teller-"


class NotConfigured(RuntimeError):
    """No LiveKit credentials. Raised rather than returning a null token.

    A token that is silently empty produces a join failure inside LiveKit's
    client, several layers from the missing environment variable that caused
    it. This fails at the point of the actual mistake.
    """


@dataclass(frozen=True)
class Credentials:
    url: str
    api_key: str
    api_secret: str


def credentials() -> Credentials | None:
    """The configured LiveKit project, or None if this deployment has none.

    None rather than raising, so `teller_available` and the health endpoint can
    ask "is video possible here?" without handling an exception. The raising
    version is `require()`.
    """
    url = os.environ.get("LIVEKIT_URL", "").strip()
    key = os.environ.get("LIVEKIT_API_KEY", "").strip()
    secret = os.environ.get("LIVEKIT_API_SECRET", "").strip()
    if not (url and key and secret):
        return None
    return Credentials(url=url, api_key=key, api_secret=secret)


def require() -> Credentials:
    creds = credentials()
    if creds is None:
        raise NotConfigured(
            "LiveKit is not configured: set LIVEKIT_URL, LIVEKIT_API_KEY and "
            "LIVEKIT_API_SECRET"
        )
    return creds


def room_name(session_id: str) -> str:
    """The room for a teller session. One room per session, always.

    Prefixed so a room in a LiveKit dashboard is identifiable as ours without
    a lookup, and so a future non-teller use of the same project cannot
    collide with a session id.
    """
    if not session_id:
        raise ValueError("a room needs a session id")
    return ROOM_PREFIX + session_id


def _b64(raw: bytes) -> str:
    """base64url without padding, as JWT requires."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _segment(payload: dict[str, Any]) -> str:
    # separators to avoid whitespace, sort_keys so the same claims always
    # produce the same token — which is what makes these testable at all.
    return _b64(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


def access_token(
    *,
    session_id: str,
    identity: str,
    name: str,
    can_publish: bool,
    now: datetime | None = None,
    creds: Credentials | None = None,
) -> str:
    """A join token for one participant, in one room, for a short window.

    Keyword-only throughout. A positional call transposing `identity` and
    `name` would mint a token whose subject is a display name — two people on
    the same call could then share an identity, and LiveKit treats identity as
    unique per room, so one would silently evict the other.

    `can_publish` is the whole permission model here: both parties on a teller
    call publish, but a future observer (a supervisor auditing a call, a
    trainee) must be able to join without a camera. Defaulting it would make
    the read-only case the easy thing to get wrong.
    """
    if not identity:
        raise ValueError("a token needs an identity")
    resolved = creds if creds is not None else require()
    issued = now or datetime.now(UTC)
    room = room_name(session_id)

    claims: dict[str, Any] = {
        "iss": resolved.api_key,
        "sub": identity,
        "name": name,
        "nbf": int((issued - CLOCK_SKEW).timestamp()),
        "exp": int((issued + TOKEN_TTL).timestamp()),
        "video": {
            # Scoped to exactly one room. Without `room`, `roomJoin` is a
            # licence to join ANY room in the project — every other customer's
            # call included.
            "room": room,
            "roomJoin": True,
            "canPublish": can_publish,
            "canSubscribe": True,
            # Data channel stays off. Nothing in this product sends data
            # messages, and an open channel between a customer and a bank
            # employee is an unaudited side channel next to a transcript we do
            # record.
            "canPublishData": False,
            # No room admin, at any level: neither party may mute, remove or
            # reconfigure the other. A teller needing to end a call ends the
            # session through our own API, where it is authorised and audited.
            "roomAdmin": False,
            "roomCreate": False,
        },
    }

    header = _segment({"alg": "HS256", "typ": "JWT"})
    body = _segment(claims)
    signing_input = f"{header}.{body}".encode("ascii")
    signature = hmac.new(
        resolved.api_secret.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    return f"{header}.{body}.{_b64(signature)}"


def decode_unverified(token: str) -> dict[str, Any]:
    """Read a token's claims WITHOUT checking its signature. Tests only.

    Named to be impossible to mistake for verification. Nothing in this service
    verifies a LiveKit token — LiveKit does — so a function that looked like a
    verifier would be an invitation to use it as one.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded))
    return claims
