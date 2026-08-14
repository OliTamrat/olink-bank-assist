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


# How far either side of `now` a rejected code is searched when explaining
# WHY it was rejected. Nothing here ever accepts a code — this window is a
# diagnostic, not an allowance, and it is deliberately far wider than
# DRIFT_STEPS so that a badly-set clock is recognisable rather than merely
# refused. Twenty minutes covers every real drift; beyond that a clock is not
# drifting, it is wrong.
DIAGNOSTIC_STEPS = 40


def explain_rejection(secret: str, code: str) -> str:
    """Why a code failed, in terms the person typing it can act on.

    "That code was not accepted" is true of two unrelated problems:

    * the code is right and the **clock** is wrong — the fix is to turn on
      automatic time on the device;
    * the code is right for a **different secret** — the app is reading an
      entry this account no longer holds, which is what happens when someone
      keeps a stale entry from an earlier attempt or from another tenant.

    Telling them apart is a search over steps, and it is cheap. Returning the
    offset in minutes rather than steps is deliberate: nobody sets their clock
    in units of thirty seconds.
    """
    candidate = code.strip().replace(" ", "")
    if not candidate.isdigit() or len(candidate) != DIGITS:
        return f"Enter the {DIGITS}-digit code from your authenticator app"

    import time as _time

    centre = step_at(_time.time())
    for offset in range(-DIAGNOSTIC_STEPS, DIAGNOSTIC_STEPS + 1):
        if hmac.compare_digest(code_for_step(secret, centre + offset), candidate):
            minutes = offset * STEP_SECONDS / 60
            direction = "ahead of" if offset > 0 else "behind"
            return (
                f"That code is correct but your device's clock is about "
                f"{abs(minutes):.0f} minute(s) {direction} ours. Turn on automatic "
                "date and time on the device, then try again."
            )
    return (
        "That code is from a different secret. Your authenticator is showing an "
        "entry this account no longer uses — delete it, scan the code on this "
        "screen again, then enter the first code it shows."
    )


def provisioning_qr_svg(uri: str) -> str:
    """The provisioning URI as an inline SVG QR code.

    Returned as markup rather than a URL because an authenticated image
    endpoint for a credential is a second thing to get wrong: it would need
    the same session check, the same rate limit, and a `Cache-Control` nobody
    would remember to set. Inline, it inherits the enrolment response's
    protections exactly and never touches disk or a cache.

    Dark modules on a WHITE plate, never on the panel's own dark surface.
    Inverted QR codes are out of spec — the finder patterns are defined as
    dark-on-light — and while some phones cope, "some phones" is not a
    property to ship on the screen that turns on two-factor. The quiet zone
    is part of that: a border of at least 4 modules is what lets a camera
    find the symbol at all, so it is set explicitly rather than left to a
    default that might change.
    """
    import io

    import segno

    buf = io.BytesIO()
    # Error correction M: ~15% recoverable, which is the level every
    # authenticator's own documentation assumes and enough for a code read off
    # a slightly dirty laptop screen at an angle.
    #
    # scale=6 means every module is SIX pixels at the SVG's intrinsic size, and
    # the stylesheet deliberately does not override that size. Photographing a
    # screen is a far harder problem than decoding a clean bitmap — glare,
    # moiré against the pixel grid, focus, angle — and the first version of
    # this shipped at scale 5 with CSS forcing the result down to 188px. That
    # is a 0.709 downscale, so every module boundary landed on a fractional
    # pixel and every edge softened, at 3.55 px per module. The code decoded
    # perfectly from a clean render and would not scan off the screen.
    segno.make(uri, error="m").save(
        buf, kind="svg", scale=6, border=4, dark="#0b1220", light="#ffffff",
        xmldecl=False, svgns=True, nl=False,
    )
    return buf.getvalue().decode("utf-8")
