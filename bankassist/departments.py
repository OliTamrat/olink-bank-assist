"""Which desk an escalation belongs on, and how fast it needs answering.

The escalation queue arrived as one undifferentiated list. Every row carried a
`reason` — complaint, human_requested, unanswered_question — but those describe
**why it left the assistant**, which is a process fact. An operator triaging a
queue needs the other axis: **what it is about**. Forty rows all reading
"unanswered_question" is, from the desk, uncategorised.

So there are two axes and they must not be conflated:

- `Handoff.reason` — why it escalated. A staffing and product signal, already
  there, unchanged by this module.
- `Handoff.department` — what it is about, and therefore who answers it.

Rules, not a model. Three reasons, in order of how much they cost to ignore:

1. **Money.** Categorising an escalation is an eight-way choice over a small,
   stable vocabulary. Spending a Gemini call on each one would put a per-row
   cost on the cheapest possible decision, and a bank's queue is the highest
   volume thing in the product.
2. **It has to be explainable.** "Why did this land on the cards desk" is a
   question a supervisor will ask, and "the model felt it was cards" is not an
   answer a bank accepts.
3. **It is testable.** The same doctrine as `classifier.py`: rules are the
   safety floor precisely because they can be pinned by a test that fails when
   somebody changes them.

**Nothing here is ever a dead end.** Anything the rules cannot place goes to
GENERAL, which is a desk somebody owns. A row nobody owns is a customer nobody
calls back — worse than a row on the wrong desk, which an operator moves in
one click.

Vocabulary in Amharic, Afaan Oromoo and Somali is drawn from terms already
verified elsewhere in this codebase (`classifier.py`'s account, complaint and
disclosure rules). Anything beyond that is a first pass and belongs in the
review workflow before a real pilot — a misrouted escalation is recoverable,
but it is still somebody waiting on the wrong desk.
"""

from __future__ import annotations

import re
from typing import Final

# ------------------------------------------------------------------ desks
#
# Named for what a retail bank actually organises around, not for our data
# model. A tenant that calls its cards desk something else renames the label;
# the code never keys on the label.

FRAUD: Final = "fraud"
CARDS: Final = "cards"
ACCOUNTS: Final = "accounts"
LENDING: Final = "lending"
PAYMENTS: Final = "payments"
DIGITAL: Final = "digital"
INTERNATIONAL: Final = "international"
GENERAL: Final = "general"

# There is deliberately no "fees" desk. Fees are a property of every product,
# not a team: a bank answers "what does a transfer cost" from the transfers
# desk and "what does the loan cost" from lending. A Fees category would
# collect questions that each belong somewhere else and call it organisation,
# which is the same undifferentiated pile this module exists to break up,
# wearing a label. Generic pricing questions with no product attached land in
# GENERAL, which somebody owns.

LABELS: Final[dict[str, str]] = {
    FRAUD: "Fraud & security",
    CARDS: "Cards & ATM",
    ACCOUNTS: "Accounts",
    LENDING: "Loans & credit",
    PAYMENTS: "Transfers & payments",
    DIGITAL: "Digital banking",
    INTERNATIONAL: "International & forex",
    GENERAL: "General enquiries",
}

# ------------------------------------------------------------- vocabulary

_RULES: Final[tuple[tuple[str, str], ...]] = (
    (
        FRAUD,
        r"\b(fraud|scam|scammed|stole|stolen|theft|unauthoris?zed|"
        r"phish\w*|hack\w*|cloned?|skimm\w*|suspicious|"
        r"someone (took|used|accessed)|not me|didn'?t (make|authorise|authorize))\b|"
        r"ተሰረቀ|ተሰርቋ|ሰረቁኝ|ማጭበርበር|ተጭበርብሬ|ተዘርፍ|"
        r"\bhatuu?\b|\bhanna\b|\bxatooyo\b",
    ),
    (
        CARDS,
        r"\b(card|cards|atm|debit|credit card|pin|chip|"
        r"cash machine|swallow(ed)?|retained|magnetic)\b|"
        r"ካርድ|ካርዴ|ፒን|ፒኔ|kaardii|\bkaarka\b",
    ),
    (
        LENDING,
        r"\b(loan|loans|lend\w*|borrow\w*|credit|mortgage|collateral|"
        r"repayment|instal?ment|interest rate|overdraft|guarantee|leas\w*)\b|"
        r"ብድር|ዕዳ|liqii|\bdeynta\b|\bamaahda\b",
    ),
    (
        INTERNATIONAL,
        r"\b(forex|foreign (exchange|currency)|exchange rate|remittance|"
        r"diaspora|swift|iban|western union|abroad|overseas|"
        r"import|export|letter of credit|dollar|euro|usd)\b|"
        r"የውጭ ምንዛሬ|ዶላር|ዲያስፖራ",
    ),
    (
        PAYMENTS,
        r"\b(transfer|transfers|send money|payment|payments|deposit|"
        r"withdraw\w*|telebirr|wallet|bill|utility|salary|standing order)\b|"
        r"ገንዘብ ማስተላለፍ|ዝውውር|ክፍያ|maallaqa erguu|\blacag\b",
    ),
    (
        DIGITAL,
        r"\b(mobile banking|internet banking|online banking|app|application "
        r"(login|password)|login|log in|otp|password|username|"
        r"ussd|\*\d{3}#|sms banking|digital)\b|"
        r"ሞባይል ባንኪንግ|መተግበሪያ|የይለፍ ቃል",
    ),
    (
        ACCOUNTS,
        r"\b(account|accounts|savings|current account|balance|statement|"
        r"open an account|close (my |the )?account|kyc|"
        r"minimum balance|joint account|beneficiar\w*)\b|"
        r"ሂሳብ|ሒሳብ|ቁጠባ|herr?e+ga|\bxisaab\b|akoonto",
    ),
)

_COMPILED: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (desk, re.compile(pattern, re.IGNORECASE)) for desk, pattern in _RULES
)

# DERIVED from the rules above, never written out by hand.
#
# The order of `_RULES` is the precedence: the first desk whose vocabulary
# appears wins, which is why FRAUD is first — "someone took money from my
# card" is a fraud matter that happens to mention a card, not a cards matter,
# and getting that backwards puts theft reports in a queue worked by close of
# business.
#
# This list was originally a second hand-written tuple in the same order, and
# a mutation test caught what that costs: reordering it changed nothing at
# all, because the matching loop reads `_RULES`. Anyone trusting the list they
# were looking at would have "fixed" a precedence bug and shipped no change.
# One source, so the display order and the deciding order cannot drift.
DEPARTMENTS: Final[tuple[str, ...]] = tuple(
    desk for desk, _ in _RULES
) + (GENERAL,)

# ------------------------------------------------------------- urgency
#
# Two levels, not five. A scale nobody can apply consistently is a scale that
# gets ignored, and the only distinction an operator acts on at 09:00 is
# "before coffee or after".

URGENT: Final = "urgent"
NORMAL: Final = "normal"
PRIORITIES: Final[tuple[str, ...]] = (URGENT, NORMAL)

# Money that has already gone, or access somebody else has. Both are losses
# that grow while the row waits, which is the only honest definition of urgent
# in a bank — everything else is a customer who is inconvenienced, and putting
# those in the same lane as a theft report is how theft reports get missed.
_URGENT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(fraud|scam|scammed|stole|stolen|theft|unauthoris?zed|hack\w*|"
    r"lost my (card|phone)|card (is )?(lost|stolen)|block (my )?card|"
    r"missing money|money (is )?gone|didn'?t receive|double charged|"
    r"charged twice|emergency|urgent)\b|"
    # ጠፍቷል / ጠፍቶብኛል / ጠፋብኝ are all "it is lost". Only one of them was here,
    # so "ካርዴ ጠፍቷል" — my card is lost, the plainest way to say it — was
    # routed as an ordinary question while the English was urgent. An
    # asymmetry like that makes the product worse for exactly the customers
    # it is built for.
    r"ተሰረቀ|ተሰርቋ|ሰረቁኝ|ጠፋብኝ|ጠፍቷል|ጠፍቶብኛል|ማጭበርበር|አስቸኳይ|"
    r"\bbade\b|\bbadee\b|\blumay\b|"
    r"\bhatuu?\b|\bxatooyo\b|\bdegdeg\b",
    re.IGNORECASE,
)


def classify(text: str, *, titles: tuple[str, ...] = ()) -> str:
    """Which desk this belongs on.

    `titles` are the knowledge-base articles retrieval matched, if any. They
    are consulted only when the customer's own words place nothing, because
    they are a weaker signal: retrieval returning the loans article for a
    question about a fee means the fee question was asked near loan wording,
    not that it is a lending matter. Weaker than the customer's words, better
    than a shrug.
    """
    for desk, pattern in _COMPILED:
        if pattern.search(text):
            return desk
    for title in titles:
        for desk, pattern in _COMPILED:
            if pattern.search(title):
                return desk
    return GENERAL


def priority(text: str) -> str:
    """`urgent` when money has already moved or somebody else has access."""
    return URGENT if _URGENT_RE.search(text) else NORMAL


def label(department: str | None) -> str:
    """A desk's human name, for a screen or a report."""
    return LABELS.get(department or GENERAL, LABELS[GENERAL])
