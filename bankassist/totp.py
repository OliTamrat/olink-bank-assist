"""Time-based one-time passwords (RFC 6238) and single-use recovery codes.

**Written out rather than pulled in, and the reason is verification.** TOTP is
HMAC-SHA1 over a counter — about twenty lines of `hmac` and `base64` — and
RFC 6238 ships published test vectors. A hand-written implementation can be
proved correct against the standard itself, in this repo's own test suite,
with no network and no trust in a third party's release process. A dependency
could only be trusted. That is the same trade the dependency-free BM25
retriever makes.

The pieces here are pure functions over their arguments — no database, no
clock of their own. `now` is always passed in, so drift, replay and expiry are
all testable without freezing time globally.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote

# RFC 6238 §4: 30 seconds is the reference implementation's step, and it is
# what every authenticator app assumes. Changing it silently breaks every
# already-enrolled device, so it is a constant rather than a setting.
STEP_SECONDS = 30
DIGITS = 6

# RFC 4226 §4 requires a shared secret of at least 128 bits and recommends
# 160. Twenty bytes is 160 bits, and encodes to exactly 32 base32 characters
# with no padding — which matters because some authenticator apps reject a
# secret containing "=".
SECRET_BYTES = 20

# How many steps either side of `now` are accepted. One step (±30s) is the
# usual allowance for a phone clock that has drifted and for the seconds a
# person spends typing. Two would double the window an intercepted code stays
# usable for; zero would reject a correct code typed a moment too late, which
# is how a security feature becomes the reason somebody turns it off.
DRIFT_STEPS = 1


def generate_secret() -> str:
    """A fresh base32 secret, in the form an authenticator app expects."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _normalise(secret: str) -> bytes:
    """Base32 back to bytes, tolerant of how people retype a secret.

    Authenticator apps display the secret in spaced groups and users paste it
    back with the spacing intact and the case flattened. Rejecting that is a
    support ticket, not security.
    """
    cleaned = secret.replace(" ", "").replace("-", "").upper()
    # b32decode demands correct padding; the stored form deliberately has none.
    padding = "=" * (-len(cleaned) % 8)
    return base64.b32decode(cleaned + padding, casefold=True)


def step_at(now: float) -> int:
    """Which 30-second step a unix timestamp falls in."""
    return int(now) // STEP_SECONDS


def code_for_step(secret: str, step: int) -> str:
    """The RFC 6238 code for one counter value.

    Straight from RFC 4226 §5.3: HMAC-SHA1 over the big-endian counter,
    dynamically truncated at the offset held in the low nibble of the last
    byte, masked to 31 bits so the result is never negative, modulo 10^digits.
    """
    digest = hmac.new(
        _normalise(secret), struct.pack(">Q", step), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFF_FFFF
    return str(truncated % (10**DIGITS)).zfill(DIGITS)


def verify(secret: str, code: str, *, now: float, last_used_step: int | None) -> int | None:
    """The step a code is valid for, or None.

    Returns the step rather than a bool so the caller can store it — which is
    what makes replay impossible. Without that, a code intercepted over a
    shoulder or out of a phone notification stays usable for the rest of its
    window and for the whole drift allowance either side of it.

    `last_used_step` is the highest step this credential has already spent.
    Anything at or below it is refused even when the arithmetic says the code
    is correct: a one-time password that works twice is not one.
    """
    candidate = code.strip().replace(" ", "")
    if not candidate.isdigit() or len(candidate) != DIGITS:
        return None
    centre = step_at(now)
    for offset in range(-DRIFT_STEPS, DRIFT_STEPS + 1):
        step = centre + offset
        if last_used_step is not None and step <= last_used_step:
            continue
        # Constant-time, like every other secret comparison in this codebase.
        # The timing signal here is small but it is free to remove.
        if hmac.compare_digest(code_for_step(secret, step), candidate):
            return step
    return None


def provisioning_uri(secret: str, *, account: str, issuer: str) -> str:
    """The `otpauth://` URI an authenticator app scans.

    The issuer appears twice on purpose — once in the label prefix and once as
    a parameter. The parameter is the modern form; the prefix is what older
    apps read, and an app that reads neither files the account under a blank
    heading, which is how somebody ends up with three unlabelled entries and
    no idea which bank each belongs to.
    """
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}"
        f"&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


# ------------------------------------------------------------- recovery

# Ten codes is the industry norm and it is a usability number rather than a
# security one: enough that losing a couple to a bad transcription does not
# strand somebody, few enough to write on one line of a notebook.
RECOVERY_CODE_COUNT = 10
# 40 bits of entropy per code, rendered as ten lowercase base32 characters in
# two groups. Far beyond guessable when the login route is rate-limited, and
# short enough to read off paper without transposing a digit.
_RECOVERY_BYTES = 5


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Codes in the form a person can copy off a screen onto paper.

    Deliberately not the same alphabet as the TOTP secret: base32 without the
    digits that read as letters, so 0/O and 1/l cannot be confused by somebody
    typing under pressure because they have lost their phone.
    """
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = []
    for _ in range(count):
        body = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{body[:5]}-{body[5:]}")
    return codes


def normalise_recovery_code(code: str) -> str:
    """One canonical form, so the hyphen and the case are never the reason a
    correct code is refused."""
    return code.strip().lower().replace(" ", "").replace("-", "")


def hash_recovery_code(code: str) -> str:
    """SHA-256, not Argon2, and that is a considered difference.

    A recovery code is 40 bits of machine-generated randomness, so it has no
    guessable structure for an offline attacker to exploit — the slow hash
    that a human-chosen password needs buys nothing here. What it would cost
    is real: ten Argon2 verifications per login attempt while looking for
    which code matches, on the one endpoint that must not become a
    denial-of-service amplifier.
    """
    return hashlib.sha256(normalise_recovery_code(code).encode("utf-8")).hexdigest()
