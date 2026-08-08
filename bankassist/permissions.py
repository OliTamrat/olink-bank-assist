"""What can be done, and who is allowed to do it.

The split here is the whole design, so it is worth stating plainly:

**Permissions live in code. Roles live in the database.**

A permission names a capability the code actually implements. There is no way
to add one without also writing the route that checks it, so a permission that
exists only in a database row is a promise nothing keeps — and worse, an
auditor reading that row would believe it. Keeping the registry in source means
the list cannot drift from the routes, and a test can prove it (see
`tests/test_permissions.py`, which fails if a route guards a permission this
module has never heard of).

A role is org structure: which jobs exist at *this* bank and what each one may
touch. That differs per tenant, changes when a bank reorganises, and must not
require a deploy. So roles are rows, and the built-in two are seeded rows
rather than special cases in code.

This is what the scope document meant by "roles are named bundles of
permissions, stored as data". The earlier draft compared `user.role == "admin"`
inside route handlers, which made every new distinction a code change plus a
migration, gave no tenant its own structure, and answered the auditor's
question "who can do what here" with an enum buried in source.
"""

from __future__ import annotations

from typing import Final


class Perm:
    """The complete set of capabilities the admin API exposes.

    String constants rather than an Enum: these values are stored in a database
    column and appear in an exported permission matrix, so the wire format is
    the thing that matters and an Enum would only add a `.value` at every use.
    """

    ANALYTICS_READ: Final = "analytics.read"
    """Aggregate numbers. Contact details are redacted before they get here."""

    CONVERSATIONS_READ: Final = "conversations.read"
    """Customer transcripts, verbatim.

    Its own permission even though both built-in roles hold it. Transcripts are
    customer personal data and analytics is aggregated — the first bank that
    wants a manager who sees the numbers but not what people typed gets that by
    editing a role, with no schema change and no deploy. Under Art. 22 of the
    data-protection proclamation that distinction is likely to be asked for.
    """

    HANDOFFS_READ: Final = "handoffs.read"
    """The escalation queue, including the customer's name and phone number."""

    HANDOFFS_RESOLVE: Final = "handoffs.resolve"
    """Close and reopen. The day job of a contact-centre agent."""

    GAPS_READ: Final = "gaps.read"
    """Questions the bank has no published answer for."""

    DOCUMENTS_READ: Final = "documents.read"

    DOCUMENTS_WRITE: Final = "documents.write"
    """Create, edit and delete the source content.

    Separated from reading because this is what the assistant says to
    customers. Someone who can rewrite a fee schedule can change what every
    customer is told a transfer costs.
    """

    INTEGRATIONS_MANAGE: Final = "integrations.manage"
    """Telegram connection and the handoff webhook.

    The sharpest reason the operator/admin line exists at all: the webhook
    decides where customers' names and phone numbers are delivered, and the
    person calling customers back is not the person who should be repointing
    it.
    """

    AUDIT_READ: Final = "audit.read"
    """The full record of who did what in this panel.

    Its own permission, and deliberately not part of the read-everything
    bundle. Reviewing colleagues' actions is a management function rather than
    part of working the queue, and an operator who can see that a manager
    disabled someone's account on Tuesday has been given something nobody
    decided to give them.

    Separating it also means a bank can hand audit access to a compliance
    officer who should see nothing else — which is precisely the person most
    likely to ask for it, and exactly what permissions-as-data is for.
    """

    USERS_MANAGE: Final = "users.manage"
    """Create, disable and re-role colleagues.

    Holding this is equivalent to holding every other permission, since anyone
    who can create a user can create one with any role. That is not a flaw to
    patch — it is what "administrator" means — but it is the reason this
    permission should be given to as few people as a bank can manage with.
    """


ALL: Final[tuple[str, ...]] = (
    Perm.ANALYTICS_READ,
    Perm.CONVERSATIONS_READ,
    Perm.HANDOFFS_READ,
    Perm.HANDOFFS_RESOLVE,
    Perm.GAPS_READ,
    Perm.DOCUMENTS_READ,
    Perm.DOCUMENTS_WRITE,
    Perm.INTEGRATIONS_MANAGE,
    Perm.AUDIT_READ,
    Perm.USERS_MANAGE,
)

_READ_ONLY: Final[tuple[str, ...]] = (
    Perm.ANALYTICS_READ,
    Perm.CONVERSATIONS_READ,
    Perm.HANDOFFS_READ,
    Perm.GAPS_READ,
    Perm.DOCUMENTS_READ,
)

OPERATOR: Final = "operator"
ADMIN: Final = "admin"

BUILTIN_ROLES: Final[dict[str, tuple[str, ...]]] = {
    # Everything readable, plus the queue work they are employed to do. An
    # operator can resolve a customer's escalation and cannot change what the
    # assistant tells the next customer.
    OPERATOR: (*_READ_ONLY, Perm.HANDOFFS_RESOLVE),
    # Deliberately every permission, listed rather than computed. `ALL` would
    # silently grant each new permission to this role the moment it is added,
    # which is the wrong default for the role that already has the most reach —
    # the grant should be a decision someone made, visible in a diff.
    ADMIN: (
        *_READ_ONLY,
        Perm.HANDOFFS_RESOLVE,
        Perm.DOCUMENTS_WRITE,
        Perm.INTEGRATIONS_MANAGE,
        Perm.AUDIT_READ,
        Perm.USERS_MANAGE,
    ),
}

BUILTIN_DESCRIPTIONS: Final[dict[str, str]] = {
    OPERATOR: "Works the escalation queue. Reads everything, changes nothing "
    "the assistant says.",
    ADMIN: "Manages content, integrations and colleagues.",
}
