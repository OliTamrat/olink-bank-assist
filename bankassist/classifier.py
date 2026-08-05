"""Language detection + intent classification.

Rules-first (deterministic, testable, zero-latency, works offline). An LLM
refinement pass can be layered on in Phase 2, but the rules stay as the
safety floor: the allowlist decision must never depend solely on a model.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- language

_ETHIOPIC = re.compile(r"[ሀ-፿]")
# The glottal series spelled with አ vs ኣ is the quickest orthographic tell
# between Amharic and Tigrinya in short chat messages.
_TIGRINYA_TELL = re.compile(r"[ኣ]|እየ|ኢኹም|ዲኹም|እዩ\b")

_OROMO_WORDS = {
    "akkam", "maaloo", "baankii", "herrega", "herreega", "maallaqa", "liqii",
    "kaffaltii", "tajaajila", "waan", "akkamitti", "danda", "qaba", "kootii",
    "koo", "banuu", "guyyaa", "hangam",
}
_SOMALI_WORDS = {
    "waan", "waxaan", "lacag", "lacagta", "bangiga", "bangi", "xisaab",
    "xisaabta", "sidee", "fadlan", "furaa", "furo", "maxay", "immisa",
    "adeegga", "kaarka",
}
_ENGLISH_WORDS = {
    "the", "how", "what", "is", "my", "account", "open", "can", "i", "to",
    "loan", "deposit", "rate", "card", "bank", "money",
}


def detect_language(text: str) -> str | None:
    """Best-effort detection; None means 'no signal, keep conversation default'."""
    if _ETHIOPIC.search(text):
        return "ti" if _TIGRINYA_TELL.search(text) else "am"
    words = set(re.findall(r"[a-z']+", text.lower()))
    if not words:
        return None
    om = len(words & _OROMO_WORDS)
    so = len(words & _SOMALI_WORDS)
    en = len(words & _ENGLISH_WORDS)
    best = max(om, so, en)
    if best == 0:
        return None
    if best == en:
        return "en"
    # "waan" is in both lists; prefer the language with more distinct hits.
    return "om" if om >= so else "so"


# ---------------------------------------------------------------- intent

GREETING = "greeting"
ACCOUNT_SPECIFIC = "account_specific"
INVESTMENT_ADVICE = "investment_advice"
COMPLAINT = "complaint"
QUESTION = "question"  # product / how-to / education — the answerable bucket

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|selam|salam|salaan|"
    r"akkam|ashamaa?|ሰላም|ሰላምታ|ጤና ይስጥልኝ|ከመይ)\W*$",
    re.IGNORECASE,
)

_ACCOUNT_RE = re.compile(
    r"\bmy (account|balance|card|statement|loan|pin|transaction)|"
    r"\b(check|what('| i)?s) my\b|"
    # Third-person / social-engineering phrasing for the same request — a
    # caller impersonating staff or a relative won't say "my" balance, but
    # this is still a request for individual account data and must get the
    # same security refusal, not fall through to a generic "I don't know".
    r"\b(give|tell|send) (me|us|her|him|them) (the |her |his |their )?balance\b|"
    r"\bbalance (for|of|on) account\b|"
    r"\boverride (the )?security\b|"
    r"\bባላንስ|ቀሪ ሂሳቤ|ሂሳቤ|ካርዴ|"
    r"herrega koo|kaardii koo|xisaabtayda|kaarkayga",
    re.IGNORECASE,
)

_ADVICE_RE = re.compile(
    r"\bshould i (invest|buy|sell|put)|\bis it (a good|worth)|"
    r"\bwhich (stock|share|investment|bond)|\bwhat should i (invest|buy)|"
    r"\brecommend .*(stock|share|invest)|ልግዛ|ልሽጥ|ኢንቨስት ላድርግ|"
    r"bitaachuu qabaa?|maalgashado",
    re.IGNORECASE,
)

_COMPLAINT_RE = re.compile(
    r"\b(complaint|complain|stole|stolen|unauthorized|unauthorised|"
    r"missing money|lost my money|terrible|worst|angry|not working|failed transfer|"
    r"(got|been|was) scammed|victim of fraud|fraud on my account|"
    r"report(ed|ing)? (a )?fraud)|"
    r"ቅሬታ|ተጭበርብሬ|ጠፋብኝ|ማጭበርበር",
    re.IGNORECASE,
)


def classify_intent(text: str) -> str:
    if _GREETING_RE.match(text):
        return GREETING
    if _COMPLAINT_RE.search(text):
        return COMPLAINT
    if _ACCOUNT_RE.search(text):
        return ACCOUNT_SPECIFIC
    if _ADVICE_RE.search(text):
        return INVESTMENT_ADVICE
    return QUESTION


# The auto-answer allowlist, same doctrine as Olink Dispatch: only intents
# named here are answered autonomously; everything else routes to a human
# path or a safety template.
AUTO_ANSWER_INTENTS = frozenset({GREETING, QUESTION, INVESTMENT_ADVICE})
