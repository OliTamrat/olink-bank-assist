"""LiveKit join tokens.

A token is the only thing standing between a stranger and someone else's
banking call, so these tests are about what a token does NOT grant as much as
what it does: one room, no admin, no data channel, and an expiry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from bankassist import livekit

CREDS = livekit.Credentials(
    url="wss://example.livekit.cloud", api_key="APItest", api_secret="s" * 32
)


def _token(**kw: object) -> str:
    args: dict[str, object] = {
        "session_id": "11111111-2222-3333-4444-555555555555",
        "identity": "customer-1",
        "name": "Customer",
        "can_publish": True,
        "creds": CREDS,
    }
    args.update(kw)
    return livekit.access_token(**args)  # type: ignore[arg-type]


# ------------------------------------------------------------------ scoping


def test_a_token_is_scoped_to_one_room() -> None:
    """The control that matters most.

    Without `room`, `roomJoin` is a licence to join ANY room in the project —
    every other customer's call included. A token that works everywhere looks
    identical to a correct one until somebody tries it on another room.
    """
    claims = livekit.decode_unverified(_token())
    assert claims["video"]["room"] == livekit.room_name(
        "11111111-2222-3333-4444-555555555555"
    )
    assert claims["video"]["roomJoin"] is True


def test_two_sessions_never_share_a_room() -> None:
    assert livekit.room_name("a") != livekit.room_name("b")


def test_a_room_name_is_not_guessable_from_the_bank() -> None:
    """It is derived from the session id and nothing else.

    A room named after a bank slug or a conversation id would be guessable by
    anyone who has seen one — and a guessable room plus a self-minted token is
    how a stranger joins a stranger's banking call.
    """
    room = livekit.room_name("11111111-2222-3333-4444-555555555555")
    assert "11111111-2222-3333-4444-555555555555" in room
    for leak in ("demo", "cbe", "dashen", "awash"):
        assert leak not in room


def test_a_room_needs_a_session() -> None:
    with pytest.raises(ValueError):
        livekit.room_name("")


# -------------------------------------------------------------- permissions


def test_nobody_gets_room_admin() -> None:
    """Neither party may mute, remove or reconfigure the other. A teller
    ending a call does it through our API, where it is authorised and audited.
    """
    for publish in (True, False):
        video = livekit.decode_unverified(_token(can_publish=publish))["video"]
        assert video["roomAdmin"] is False
        assert video["roomCreate"] is False


def test_the_data_channel_stays_shut() -> None:
    """An open data channel between a customer and a bank employee is an
    unaudited side channel, next to a chat transcript we do record."""
    assert livekit.decode_unverified(_token())["video"]["canPublishData"] is False


def test_an_observer_can_watch_without_a_camera() -> None:
    """A supervisor auditing a call, or a trainee. They must be able to join
    without publishing — and `can_publish` has no default, so the read-only
    case cannot be reached by forgetting an argument."""
    video = livekit.decode_unverified(_token(can_publish=False))["video"]
    assert video["canPublish"] is False
    assert video["canSubscribe"] is True


def test_publishing_is_never_implied() -> None:
    """Keyword-only and undefaulted. A caller that forgets it fails loudly
    rather than minting a token with whatever the default happened to be."""
    with pytest.raises(TypeError):
        livekit.access_token(  # type: ignore[call-arg]
            session_id="s", identity="i", name="n", creds=CREDS
        )


def test_a_token_must_name_someone() -> None:
    with pytest.raises(ValueError):
        _token(identity="")


# ------------------------------------------------------------------- expiry


def test_a_token_expires() -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    claims = livekit.decode_unverified(_token(now=now))
    assert claims["exp"] == int((now + livekit.TOKEN_TTL).timestamp())
    assert claims["exp"] > claims["nbf"]


def test_a_token_outlives_a_realistic_queue_wait() -> None:
    """A customer may be granted a token while still waiting. A token that
    expires in the waiting room turns an ordinary wait into a failed call."""
    assert timedelta(minutes=5) <= livekit.TOKEN_TTL


def test_a_fast_device_clock_does_not_reject_its_own_token() -> None:
    """Phones in the field are not NTP-synced. Without backdating `nbf`, a
    device a minute ahead rejects the token as not-yet-valid and the failure
    reads as a server fault."""
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    claims = livekit.decode_unverified(_token(now=now))
    assert claims["nbf"] <= int((now - timedelta(minutes=1)).timestamp())


# ---------------------------------------------------------------- signature


def test_the_signature_is_hs256_over_the_header_and_body() -> None:
    """Hand-rolled, so it is verified here against the stdlib rather than
    assumed. LiveKit rejecting every token is a failure that would otherwise
    only appear against a live project."""
    token = _token()
    header, body, sig = token.split(".")
    expected = hmac.new(
        CREDS.api_secret.encode(), f"{header}.{body}".encode(), hashlib.sha256
    ).digest()
    assert sig == base64.urlsafe_b64encode(expected).rstrip(b"=").decode()


def test_the_header_declares_hs256() -> None:
    header = _token().split(".")[0]
    padded = header + "=" * (-len(header) % 4)
    assert json.loads(base64.urlsafe_b64decode(padded)) == {
        "alg": "HS256", "typ": "JWT"
    }


def test_a_token_carries_no_padding() -> None:
    """base64url in a JWT is unpadded. A stray '=' makes the token invalid in
    a way that only shows up as a rejected join."""
    assert "=" not in _token()


def test_the_issuer_is_the_api_key() -> None:
    """How LiveKit knows which secret to verify against."""
    assert livekit.decode_unverified(_token())["iss"] == CREDS.api_key


def test_a_different_secret_produces_a_different_signature() -> None:
    other = livekit.Credentials(url=CREDS.url, api_key=CREDS.api_key, api_secret="x" * 32)
    assert _token().split(".")[2] != _token(creds=other).split(".")[2]


# ------------------------------------------------------------ configuration


def test_an_unconfigured_deployment_reports_it_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    assert livekit.credentials() is None
    with pytest.raises(livekit.NotConfigured):
        livekit.require()


def test_a_half_configured_deployment_counts_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The likeliest real misconfiguration: one of the three set, or a secret
    that failed to mount and arrived empty. Treating that as configured mints
    tokens signed with an empty string, which LiveKit rejects with an error
    that says nothing about the missing variable."""
    monkeypatch.setenv("LIVEKIT_URL", "wss://x.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APItest")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "")
    assert livekit.credentials() is None


def test_whitespace_around_a_mounted_secret_is_trimmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A secret written with `echo` carries a trailing newline. Signing with
    it produces a valid-looking token that fails verification — the exact
    class of bug deploy.yml already works around for the database URL."""
    monkeypatch.setenv("LIVEKIT_URL", " wss://x.livekit.cloud\n")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APItest\n")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "  secret  ")
    creds = livekit.credentials()
    assert creds is not None
    assert creds.api_secret == "secret"
    assert creds.url == "wss://x.livekit.cloud"
