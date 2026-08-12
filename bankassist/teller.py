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


# --------------------------------------------------------------- chat roles
#
# What a live teller's typed message is stored as. A THIRD role, never
# "assistant".
#
# The assistant's whole promise to a bank is that everything under its name
# came from the bank's own indexed content. Filing a human's typing under the
# same role would put words the assistant never produced into its transcript,
# its analytics and any audit of what it said — and there would be no way to
# tell them apart afterwards. It would also make the outcome column lie, since
# a teller's sentence has no retrieval outcome.
#
# Analytics filter on `role == "assistant"` explicitly, so this role is
# counted in neither the assistant's tallies nor the customer's.
MESSAGE_ROLE: Final = "teller"


# ------------------------------------------------------------------ routing
#
# Which waiting customer a given teller should take next.
#
# The rule this file already states is that a queue is worked oldest-first,
# because anything else means the person who has waited longest keeps losing.
# Language routing bends that, and expertise routing bends it again, and the
# bending has to be bounded:
#
# - A teller who speaks the customer's language serves them better than one
#   who does not, so matches come first.
# - Within a language group, a teller who knows the desk the question is
#   about (cards, lending, fraud — the same eight desks every escalation
#   lands on) serves them better than one who does not. Language outranks
#   expertise deliberately: a conversation you cannot hold at all is worse
#   than a desk you know less well.
# - A customer whose language or desk nobody has declared must not wait
#   forever behind an endless supply of matched ones. Past `PATIENCE` their
#   wait outranks everybody's match of either kind.
# - Nothing is ever HIDDEN. A teller can always take any session; routing
#   changes the order it is offered in, not what is permitted. A hard filter
#   would strand the one customer nobody can serve, which is the opposite of
#   what routing them is for.

PATIENCE: Final = 180  # seconds before waiting time outranks any match


def speaks(languages: list[str] | None, language: str | None) -> bool:
    """Can this teller hold the conversation?

    An undeclared teller (None or empty) speaks everything. Every teller
    starts undeclared, so the opposite reading would empty every queue on the
    day this ships. Declaring narrows what reaches you first; it never takes
    work away from a bank that has not filled the field in.

    A session with no detected language yet matches anybody — there is nothing
    to route on, and holding it back would be worse than offering it.
    """
    if not languages:
        return True
    if not language:
        return True
    return language in languages


def covers(desks: list[str] | None, department: str | None) -> bool:
    """Does this teller's declared expertise cover the customer's question?

    Exactly `speaks()` with different nouns, on purpose — the two predicates
    must keep the same semantics or the queue becomes unexplainable:

    An undeclared teller (None or empty) covers every desk. Every teller
    starts undeclared, so the opposite reading would empty every queue on the
    day this ships. Declaring narrows what reaches you first; it never takes
    work away.

    A session with no classified department matches anybody — there is
    nothing to route on, and holding it back would be worse than offering it.
    """
    if not desks:
        return True
    if not department:
        return True
    return department in desks


def queue_order(
    sessions: list[tuple[str | None, str | None, int]],
    languages: list[str] | None,
    desks: list[str] | None = None,
) -> list[int]:
    """Indexes of `(language, department, waited_seconds)`, in offer order.

    Returns indexes rather than reordering, so the caller keeps whatever row
    objects it has and this stays free of the database.

    Two tiers. Past PATIENCE, matching stops mattering ENTIRELY and the
    longest wait wins; below it a language match comes first, an expertise
    match second within it, with the longest wait breaking ties inside each
    group so the queue stays oldest-first there.

    Both matches are deliberately absent from the starving tier's key.
    Leaving language in re-sorted the starving customers by language as well,
    so an Oromo speaker who had waited past patience still lost to an Amharic
    one who had waited less — precisely the starvation this tier exists to
    end. Caught by a test rather than by reading it back, and the same test
    now holds for expertise.
    """
    def key(i: int) -> tuple[int, int, int, int]:
        language, department, waited = sessions[i]
        if waited >= PATIENCE:
            return (0, 0, 0, -waited)
        return (
            1,
            0 if speaks(languages, language) else 1,
            0 if covers(desks, department) else 1,
            -waited,
        )

    return sorted(range(len(sessions)), key=key)
