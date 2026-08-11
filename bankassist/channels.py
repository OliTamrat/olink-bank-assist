"""Where customers can reach the assistant, and what each one actually costs.

Served to the Settings screen so the page states the position honestly instead
of showing greyed-out logos that imply a switch nobody has flipped. "Coming
soon" next to a WhatsApp mark is a promise made on a bank's behalf, and the
person reading it is deciding whether to buy.

**A channel is an adapter, not a rewrite.** The agent core takes text and a
conversation and returns a reply; it knows nothing about where the text came
from. `telegram.py` is the whole reference implementation and it is 41 lines —
an inbound webhook and an outbound send. That is why the honest answer to "can
you add WhatsApp" is "yes, and the code is small" rather than "yes" alone.

What is NOT small is everything around it. WhatsApp needs a Meta Business
account, a WhatsApp Business Account, a phone number that is not already on
WhatsApp, and Meta's review of the use case — weeks of an organisation's time,
none of it engineering, and none of it something we can do on a bank's behalf.
Recording that here is the point: the blocker is procurement, so it belongs in
front of the person who can start it.
"""

from __future__ import annotations

from typing import Any, Final

LIVE: Final = "live"
"""Working now, for this tenant."""

AVAILABLE: Final = "available"
"""Built and tested; needs a credential the bank supplies."""

PLANNED: Final = "planned"
"""Not built. Listed with what it would take, so the answer is checkable."""


CATALOGUE: Final[tuple[dict[str, Any], ...]] = (
    {
        "key": "web",
        "name": "Website widget",
        "status": LIVE,
        "blurb": "The chat bubble on your own pages. Nothing to connect — it is "
                 "live wherever you paste the embed.",
        "needs": [],
    },
    {
        "key": "telegram",
        "name": "Telegram",
        "status": AVAILABLE,
        "blurb": "Customers message your bank's bot. Widely used in Ethiopia, and "
                 "the only channel here you can turn on today without anyone's "
                 "approval.",
        "needs": ["A bot token from @BotFather — free, and takes about a minute."],
    },
    {
        "key": "whatsapp",
        "name": "WhatsApp",
        "status": PLANNED,
        "blurb": "Technically the same shape as Telegram: a webhook in, a send "
                 "call out. The work is the account, not the code.",
        "needs": [
            "A Meta Business account, verified against the bank's registration.",
            "A WhatsApp Business Account and a dedicated number not already "
            "registered on WhatsApp.",
            "Meta's review of the use case, and message templates approved for "
            "anything you send first rather than reply to.",
        ],
    },
    {
        "key": "messenger",
        "name": "Facebook Messenger",
        "status": PLANNED,
        "blurb": "Same Meta plumbing as WhatsApp, so doing one makes the other "
                 "cheap. Worth pairing with whichever you start.",
        "needs": [
            "A Facebook Page for the bank and a Meta app with Page messaging "
            "permissions.",
        ],
    },
    {
        "key": "instagram",
        "name": "Instagram Direct",
        "status": PLANNED,
        "blurb": "Reaches a younger audience than the branch does. Requires the "
                 "account to be a professional one linked to the Page.",
        "needs": ["An Instagram professional account linked to the bank's Page."],
    },
    {
        "key": "viber",
        "name": "Viber",
        "status": AVAILABLE,
        "blurb": "Customers message your bank's Viber account. Still common in "
                 "parts of the diaspora, and — like Telegram — it can be turned "
                 "on today without anyone's approval.",
        "needs": [
            "A bot account from partners.viber.com — self-serve, and it issues "
            "the authentication token immediately.",
        ],
    },
    {
        "key": "sms",
        "name": "SMS",
        "status": PLANNED,
        "blurb": "The only channel that reaches a customer with no smartphone and "
                 "no data, which in rural Ethiopia is the point. Also the only "
                 "one that costs money per message.",
        "needs": [
            "A shortcode or sender ID, and an aggregator agreement — in Ethiopia "
            "that means Ethio Telecom.",
            "A per-message budget: unlike the others, every reply has a price.",
        ],
    },
)


def catalogue(
    *, telegram_connected: bool, viber_connected: bool = False
) -> list[dict[str, Any]]:
    """The catalogue with this tenant's live state folded in."""
    connected = {"telegram": telegram_connected, "viber": viber_connected}
    out: list[dict[str, Any]] = []
    for entry in CATALOGUE:
        row = dict(entry)
        if connected.get(str(row["key"])):
            row["status"] = LIVE
        out.append(row)
    return out
