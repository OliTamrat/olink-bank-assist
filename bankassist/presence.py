"""Who is at a desk right now, and whether a customer may be offered a call.

This exists as its own module for two reasons.

The first is architectural: both the customer's chat and the admin API need
the same answer to "can anyone actually take this call", and the answer has to
be identical in both places or the assistant will promise something the widget
then refuses to offer. Putting it in `api.py` made `agent.py` unable to reach
it without a circular import, which is how the two drifted apart in the first
place — the assistant said "I've passed you to a person" while the widget,
reading the same tenant, showed no button.

The second is a design correction. Presence used to be a side effect of
watching the queue page: whoever had it open was "on duty", and closing the tab
or navigating to Reports silently took the bank off the air. That made an
invisible product-level switch out of a browser tab. Duty is now something a
teller DECLARES — an explicit toggle with a heartbeat behind it — so being on
the air is a choice, and stepping away from it is one too.

`teller_seen_at` carries both halves of that: NULL means off duty (explicitly,
or never on), and a timestamp older than `TELLER_PRESENCE_WINDOW` means the
browser stopped reporting — a closed laptop, a dead network, a crashed tab.
Both resolve to "do not offer this customer a call", which is the safe
direction: an unoffered call is a disappointment, an offered one that nobody
answers is a person watching a counter climb.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import livekit, permissions
from .models import Bank, Role, RolePermission, User

# How stale a heartbeat may get before a teller stops counting as present.
#
# 90 seconds against a 30-second heartbeat: two missed beats are tolerated, so
# a slow network or a browser throttling a background tab does not flicker the
# bank off the air, while a closed laptop clears within about a minute and a
# half. Longer would leave customers queueing for someone who left; much
# shorter would need a chattier heartbeat to stay stable.
TELLER_PRESENCE_WINDOW = timedelta(seconds=90)

# How often the admin shell reports in. Served to the browser rather than
# hard-coded there, so the two halves of the window can never drift apart.
HEARTBEAT_SECONDS = 30


def set_duty(user: User, *, on_duty: bool, now: datetime | None = None) -> None:
    """Record a teller going on or off duty.

    Off duty clears the timestamp rather than backdating it. NULL is a
    statement — "this person is not taking calls" — where an old timestamp is
    merely evidence that they were once here, and the two want to be
    distinguishable when reading a row.
    """
    user.teller_seen_at = (now or datetime.now(UTC)) if on_duty else None


def on_duty(user: User, now: datetime | None = None) -> bool:
    """Whether this teller's own heartbeat is current."""
    seen = user.teller_seen_at
    if seen is None:
        return False
    if seen.tzinfo is None:  # SQLite hands back naive datetimes
        seen = seen.replace(tzinfo=UTC)
    return seen >= (now or datetime.now(UTC)) - TELLER_PRESENCE_WINDOW


def teller_available(db: Session, bank: Bank) -> bool:
    """Whether this tenant can connect a customer to a person right now.

    Three conditions, and every one of them has produced a real failure when
    it was missing:

    1. The bank offers the service at all. It defaults off because offering
       live video is a decision a bank makes, not one a deploy makes.
    2. There is a media layer. A deployment with the feature switched on but
       LIVEKIT_* unset would otherwise advertise video it cannot carry.
    3. Somebody is on duty and reporting in. Scoped by PERMISSION, not by role
       name, so a bank that renames `teller` to `agent` or splits it in two
       keeps working — and so a supervisor who can read the queue but not
       answer it never lights the button with nobody behind it.
    """
    if not bank.teller_enabled:
        return False
    if livekit.credentials() is None:
        return False
    cutoff = datetime.now(UTC) - TELLER_PRESENCE_WINDOW
    return db.execute(
        select(User.id)
        .join(Role, Role.id == User.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .where(
            User.bank_id == bank.id,
            User.disabled_at.is_(None),
            User.teller_seen_at.is_not(None),
            User.teller_seen_at >= cutoff,
            RolePermission.permission == permissions.Perm.TELLER_SERVE,
        )
        .limit(1)
    ).first() is not None
