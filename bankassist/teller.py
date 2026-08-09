"""Teller-session lifecycle. Pure logic, no database.

Everything here is a decision about what a session may do next, expressed
without a Session object, so the rules can be tested exhaustively and read
without a schema in your head. The database side lives in api.py; this file
owns the state machine and the scope model.

See `docs/video-teller.md` for why the product looks like this. Two boundaries
from that document are enforced HERE rather than by convention, because they
are the ones a future change is most likely to erode by accident:

- A session is never addressed at a customer. `request()` is the only way one
  comes into existence and it is called by the customer's own chat. There is
  no constructor that takes a customer as a target. If people are trained to
  accept incoming calls "from the bank", that becomes a fraud vector pointed
  at exactly the customers least able to spot it.
- No scope, at any verification level, permits moving money. `MONEY` is not a
  capability that is withheld — it is absent from every scope's grant list, so
  granting it would take a deliberate edit to a named constant rather than a
  flag flip.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------- states
#
# Spelled out rather than derived, because these strings end up in a database
# column, in the queue UI and in a bank's own reporting. A state machine whose
# names are computed is one nobody can grep for.

REQUESTED: Final = "requested"      # the customer asked; nothing has happened yet
VERIFYING: Final = "verifying"      # identity check in flight
QUEUED: Final = "queued"            # waiting for a teller
ACTIVE: Final = "active"            # a teller joined
ENDED: Final = "ended"              # finished normally, with a resolution
ABANDONED: Final = "abandoned"      # the customer left before anyone joined
FAILED: Final = "failed"            # network, token or media failure

STATES: Final[tuple[str, ...]] = (
    REQUESTED, VERIFYING, QUEUED, ACTIVE, ENDED, ABANDONED, FAILED,
)

# A session in one of these is finished and can never move again. Worth naming
# because "is this over?" is asked in several places and each open-coded
# version is a chance to forget one.
TERMINAL: Final[frozenset[str]] = frozenset({ENDED, ABANDONED, FAILED})

# Legal moves. Anything not listed is refused — a denylist would silently
# permit every state added later.
_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    REQUESTED: frozenset({VERIFYING, ABANDONED, FAILED}),
    VERIFYING: frozenset({QUEUED, ABANDONED, FAILED}),
    # QUEUED -> ABANDONED is the common exit, not an error: most people who
    # wait too long simply leave, and that is the number this feature exists
    # to move.
    QUEUED: frozenset({ACTIVE, ABANDONED, FAILED}),
    ACTIVE: frozenset({ENDED, FAILED}),
    ENDED: frozenset(),
    ABANDONED: frozenset(),
    FAILED: frozenset(),
}


class InvalidTransition(ValueError):
    """Raised rather than returning False.

    A refused transition is a bug in the caller, not a condition to branch on,
    and the two places it could go wrong quietly — a second teller claiming a
    session that is already active, and a session ending twice — are both ones
    where silence would look like success.
    """


def can_move(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


def move(current: str, target: str) -> str:
    """The new state, or raise. Returns the target so call sites read as an
    assignment rather than a check followed by an assignment."""
    if not can_move(current, target):
        raise InvalidTransition(f"{current} -> {target}")
    return target


def is_waiting(state: str) -> bool:
    """Occupying a place in the queue. Used for queue depth and for deciding
    what a customer closing their browser should collapse to."""
    return state in (REQUESTED, VERIFYING, QUEUED)


# --------------------------------------------------------------------- scopes
#
# What a teller may do, given how well the customer has been identified.

UNVERIFIED: Final = "unverified"
VERIFIED: Final = "verified"

SCOPES: Final[tuple[str, ...]] = (UNVERIFIED, VERIFIED)

# Capabilities, as things a teller can be authorised for. Named so that a
# grant is legible in a permission matrix and in an audit row.
GENERAL_GUIDANCE: Final = "general_guidance"    # products, eligibility, "which account"
OWN_RECORDS: Final = "own_records"              # this customer's application, documents
DOCUMENT_CAPTURE: Final = "document_capture"    # take an ID or a form from them
DISPUTE_INTAKE: Final = "dispute_intake"        # file a complaint on their behalf
MONEY: Final = "money"                          # deposits, withdrawals, transfers

_GRANTS: Final[dict[str, frozenset[str]]] = {
    # Everything tier 1 can do, with a person attached. Nothing specific to
    # the individual, because we do not yet know who they are.
    UNVERIFIED: frozenset({GENERAL_GUIDANCE}),
    VERIFIED: frozenset(
        {GENERAL_GUIDANCE, OWN_RECORDS, DOCUMENT_CAPTURE, DISPUTE_INTAKE}
    ),
}

# MONEY appears in no grant list. This is asserted rather than left to
# inspection, because the failure it guards against is somebody adding it to
# VERIFIED in a hurry and nothing objecting.
assert not any(MONEY in grant for grant in _GRANTS.values()), (
    "money movement is out of scope at every verification level — see "
    "docs/video-teller.md §2"
)


def allows(scope: str, capability: str) -> bool:
    """May a teller do this, at this verification level?

    Unknown scopes grant nothing rather than raising. A scope string that
    arrives from a database column somebody edited by hand should fail closed,
    and a session that can do nothing is visibly broken; one that can do
    everything is not.
    """
    return capability in _GRANTS.get(scope, frozenset())


def capabilities(scope: str) -> tuple[str, ...]:
    """Everything permitted at this level, sorted — for the UI that tells the
    customer, before they queue, what this teller will be able to help with."""
    return tuple(sorted(_GRANTS.get(scope, frozenset())))
