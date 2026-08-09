"""Fixed assistant strings in the five supported languages.

The strings themselves live in `strings.json`, not in this file. That is what
lets a reviewer edit them: `scripts/i18n_export.py` writes a TSV, a native
speaker corrects the cells, and `scripts/i18n_import.py` writes it back. When
the table lived as a Python literal, every correction had to be retyped by
hand into source — and hand-copying Ge'ez is exactly where errors enter.

EN and AM have been reviewed with care. OM, TI and SO are first-pass drafts
and must go through the review workflow in `review/README.md` before a real
bank pilot.

`_NOTES` carries the reason each string is worded the way it is. It used to be
inline comments, which meant the person doing the translating never saw any of
it — they were addressed to whoever edited the code next, not to the reviewer
who actually needed them. Now they ride along in the export's context column,
where several of them are the difference between a correct translation and a
grammatical one: "related_topics" must not become a question, "ask_contact"
has to end the turn, "ack_named" is a fragment that gets another sentence
glued to it.
"""

from __future__ import annotations

import json
from pathlib import Path

SUPPORTED_LANGUAGES = ["en", "am", "om", "ti", "so"]

LANGUAGE_NAMES = {
    "en": "English",
    "am": "አማርኛ",
    "om": "Afaan Oromoo",
    "ti": "ትግርኛ",
    "so": "Soomaali",
}

STRINGS_PATH = Path(__file__).with_name("strings.json")


def _load() -> dict[str, dict[str, str]]:
    with STRINGS_PATH.open(encoding="utf-8") as fh:
        data: dict[str, dict[str, str]] = json.load(fh)
    return data


_STRINGS: dict[str, dict[str, str]] = _load()


# What each string is for, and what a translation must preserve. Written for
# the person translating it, not for the next maintainer.
_NOTES: dict[str, str] = {
    "greeting": "First message when the customer says hello. {bank} is the bank's name.",
    "greeting_named": (
        "Same, when the customer introduced themselves. {name} is what they called "
        "themselves — keep it natural to address someone by name here."
    ),
    "ack_named": (
        "A FRAGMENT, not a sentence. Another full sentence is joined onto the end "
        "of it, so it must read as an opening, e.g. 'Thanks Oli —'. Keep whatever "
        "punctuation makes that work in your language."
    ),
    "unknown": (
        "Said when the bank's own documents do not answer the question. It must "
        "admit not knowing without sounding like a failure — the honesty is the "
        "product's selling point. Never imply an answer was given."
    ),
    "general_guidance": (
        "Appended to an answer drawn from universal banking knowledge rather than "
        "this bank's material. It must be unmistakable that the bank is NOT the "
        "source, or the bank is on the hook for something it never published."
    ),
    "related_topics": (
        "Introduces a bulleted list of topic titles that follows immediately. "
        "MUST be a statement, never a question — it used to ask 'were you asking "
        "about one of these?', which competed with the contact request below it "
        "and meant customers answered the wrong question. Ends with a colon."
    ),
    "ask_contact": (
        "The one question the turn is for. It is always the LAST thing in the "
        "message, so it must work as a closing line. Asks for a name and a phone "
        "number; an email is also accepted if the customer gives one."
    ),
    "contact_on_file": (
        "Said INSTEAD of asking again, when we already have their number. Its own "
        "short sentence on its own line. {contact} is their phone number or email."
    ),
    "no_contact_yet": (
        "Said INSTEAD of asking again, when we have NO way to reach them and have "
        "already asked as often as we are willing to. A statement of fact, not a "
        "question, and NOT a fresh request for a number — the customer has "
        "declined twice and must not be pestered a third time. It exists only "
        "so they are not left believing a callback is coming. Do not add an "
        "invitation to send details later: nothing is listening for them once "
        "the asking has stopped. Its own short sentence on its own line."
    ),
    "contact_saved": "Confirms their details were stored. {contact} is what they gave.",
    "contact_saved_named": "Same, when we also captured their name.",
    "account_help": (
        "A security refusal: the assistant cannot see anyone's account. It must be "
        "firm but not accusing — most people asking are legitimate customers who "
        "simply expected it to work. Ends by offering general help."
    ),
    "complaint_ack": (
        "For a customer reporting something wrong — theft, a failed transfer, bad "
        "service. Sympathy first, then the promise that a person will follow up."
    ),
    "human_request_ack": (
        "For a customer who asked to speak to a person, a manager or the "
        "management. NOT an apology and NOT a refusal — the request is being "
        "granted. Warm and brief; the contact request follows it."
    ),
    "advice_disclaimer": (
        "Legal boundary on any investment question: education, never personal "
        "advice, see a licensed advisor. The meaning must survive exactly."
    ),
    "fallback_intro": (
        "Introduces text quoted directly from the bank's documents, used when the "
        "AI model is unavailable. {bank} is the bank's name."
    ),
    "sources_label": "Heading over the list of documents an answer came from. One or two words.",
    "comparison_intro": (
        "For 'is another bank better?'. The assistant never comments on a rival — "
        "it pivots to this bank's own strengths. Introduces text that follows."
    ),
    "comparison_fallback": (
        "Same situation, when this bank has no 'why choose us' document. Declines "
        "the comparison and offers to talk about the bank instead."
    ),
}


def t(language: str | None, key: str, **kwargs: str) -> str:
    lang = language if language in _STRINGS else "en"
    template = _STRINGS[lang].get(key) or _STRINGS["en"][key]
    return template.format(**kwargs) if kwargs else template
