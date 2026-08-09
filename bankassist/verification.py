"""How a customer's identity gets established, and what that is worth.

Two methods, and the design exists so the second can replace the first without
anything above it changing.

**teller_attested** — what ships first, and what needs nothing from anybody.
The customer shows their Fayda ID to the camera; the teller compares it
against the account record already open on their own core-banking screen and
asks questions only the account holder could answer. The teller then attests.
No integration, no registration, works today, and works for a customer whose
phone cannot do face capture.

**fayda_oidc** — Fayda's eSignet is an OpenID Provider, so this is a standard
OIDC flow rather than anything bespoke: the customer authenticates directly
with Fayda and we receive a signed assertion. Reserved here, not implemented,
because relying-party registration is a real process with a real queue. When
it lands it is a new METHOD, not a new model.

---

Three decisions worth stating outright, because each is the kind that gets
quietly reversed later.

**The ID image is shown, never stored.** It travels through the live session
to the teller's screen and is not written anywhere. Storing it would make this
the most sensitive table in the product — a library of national ID documents —
in exchange for nothing, since the bank's own system is the system of record
and the teller is looking at it there anyway. Under Art. 22 that library is a
liability with no matching asset.

**We do not keep the Fayda number.** `reference` is a short tail (last four
digits) for reconciling a dispute, never the 12-digit FIN. Holding the full
number would link every one of our rows to a national identity for a benefit
the bank already has in its own records.

**An attestation records what was actually checked.** A teller ticking
"verified" having asked nothing is not verification, and a scheme that cannot
tell the difference is decoration. `attest()` refuses an attestation that does
not meet the bar, so the control is in code rather than in training.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ------------------------------------------------------------------- methods

TELLER_ATTESTED: Final = "teller_attested"
FAYDA_OIDC: Final = "fayda_oidc"

METHODS: Final[tuple[str, ...]] = (TELLER_ATTESTED, FAYDA_OIDC)

# Human labels, for the session record and anywhere a supervisor reads one.
# A method nobody can name is a method nobody can audit.
METHOD_LABELS: Final[dict[str, str]] = {
    TELLER_ATTESTED: "Checked by a teller against the account record",
    FAYDA_OIDC: "Verified by Fayda",
}

# -------------------------------------------------------------------- checks
#
# What a teller can actually confirm. Named individually because "verified" as
# a single boolean throws away the only information a dispute needs: not
# whether someone said yes, but what they looked at.

ID_DOCUMENT: Final = "id_document"
"""The Fayda ID was shown on camera and matches the name on the account."""

ID_PHOTO_MATCHES: Final = "id_photo_matches"
"""The face on the ID is the face on the call."""

ACCOUNT_DETAIL: Final = "account_detail"
"""A question only the account holder could answer — recent activity, the
branch it was opened at, details the bank holds and a stranger does not.

Deliberately not enumerated here. What is safe to ask changes with what a bank
holds and with what has leaked, and a fixed list in our source would become a
script for the very people it is meant to exclude.
"""

CHECKS: Final[tuple[str, ...]] = (ID_DOCUMENT, ID_PHOTO_MATCHES, ACCOUNT_DETAIL)

CHECK_LABELS: Final[dict[str, str]] = {
    ID_DOCUMENT: "Fayda ID shown and matches the account name",
    ID_PHOTO_MATCHES: "Photo on the ID matches the person on the call",
    ACCOUNT_DETAIL: "Answered a question only the account holder could",
}

# The bar for a teller-attested verification.
#
# Both, not either. An ID held to a camera is a picture of a document, and a
# picture can be of somebody else's document — the photo match is what ties it
# to the person on the call. And the document alone proves who they are, not
# that the account is theirs; the account question is what closes that gap.
#
# ID_PHOTO_MATCHES is not required: on an audio-only session — which outside
# Addis is the common case, not the exception — there is no face to compare,
# and requiring it would mean identity verification silently stopped working
# for the customers with the worst connections. It is recorded when it happens
# and it strengthens the record; it is not the load-bearing check.
REQUIRED_CHECKS: Final[frozenset[str]] = frozenset({ID_DOCUMENT, ACCOUNT_DETAIL})


class AttestationRejected(ValueError):
    """The teller did not do enough to call this verified.

    Raised rather than returning a flag, for the same reason the state machine
    raises: a rejected attestation is a caller bug — the UI should not have
    offered the button — and a silent no-op would leave a session showing
    "unverified" with nobody able to say why.
    """


@dataclass(frozen=True)
class Attestation:
    """What a teller confirmed, and who is answerable for it.

    Frozen because this is evidence. A record of who vouched for a stranger's
    identity should not be something later code can quietly edit.
    """

    method: str
    checks: frozenset[str]
    teller_user_id: str
    reference: str | None = None

    @property
    def label(self) -> str:
        return METHOD_LABELS.get(self.method, self.method)

    def describes(self) -> tuple[str, ...]:
        """Human-readable, in the fixed order of CHECKS rather than set order,
        so two identical attestations always read identically."""
        return tuple(CHECK_LABELS[c] for c in CHECKS if c in self.checks)


def tail(fayda_number: str | None, keep: int = 4) -> str | None:
    """The last few digits of a Fayda number, and nothing else.

    Everything non-numeric is dropped first, so a number typed with spaces or
    dashes reduces the same way every time — otherwise the same customer
    reconciles differently depending on how a teller typed it.

    Returns None for anything too short to be a real number rather than
    returning it whole. The failure this guards is the obvious one: a
    truncation helper that quietly hands back the full value when it cannot
    truncate is worse than no helper, because every call site believes it is
    safe.
    """
    if not fayda_number:
        return None
    digits = "".join(ch for ch in fayda_number if ch.isdigit())
    if len(digits) <= keep:
        return None
    return digits[-keep:]


def attest(
    *,
    checks: frozenset[str] | set[str],
    teller_user_id: str,
    fayda_number: str | None = None,
) -> Attestation:
    """Record that a teller verified this customer, or refuse to.

    Keyword-only throughout. The two string arguments are a user id and a
    national ID number, and a positional call that transposed them would store
    a national ID in a column read as "who vouched for this" — silently, and
    forever.
    """
    checks = frozenset(checks)
    unknown = checks - set(CHECKS)
    if unknown:
        raise AttestationRejected(f"unknown checks: {sorted(unknown)}")
    missing = REQUIRED_CHECKS - checks
    if missing:
        raise AttestationRejected(
            "not enough was checked to call this verified — missing: "
            + ", ".join(CHECK_LABELS[c] for c in CHECKS if c in missing)
        )
    if not teller_user_id:
        raise AttestationRejected("an attestation must name the teller making it")
    return Attestation(
        method=TELLER_ATTESTED,
        checks=checks,
        teller_user_id=teller_user_id,
        reference=tail(fayda_number),
    )
