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
COMPARISON = "comparison"  # "is X better than us?" — answer confidently, never via retrieval
QUESTION = "question"  # product / how-to / education — the answerable bucket

# Greeting vocabulary across the five supported languages, including the
# companions that make up a full greeting ("akkam jirta", "ደህና ነህ") — those
# are part of the greeting, not a question, and stripping them is what lets
# a whole greeting resolve to nothing left over.
_GREET_WORD = (
    r"hi|hello|hey|hallo|good (morning|afternoon|evening)|greetings|"
    r"selam|selaam|salam|salaam|salaan|nagaa|naga|"
    r"akkam|akam|ashamaa?|jirta|jirtu|jirtan|fayyaa|"
    r"dehna|dehina|nagaadha|iska warran|sidee tahay|subax wanaagsan|"
    r"ሰላም|ሰላምታ|ጤና ይስጥልኝ|ደህና|ደሕና|ነህ|ነሽ|ኖት|ከመይ|ሓዲኹም|እንደምን|አለህ|አለሽ"
)

# One or more greeting words in any order, separated only by spaces or
# punctuation. The old pattern allowed exactly ONE, so the most natural
# openings a bilingual customer types — "Hi akkam?", "Hello selam",
# "akkam jirta?" — fell through to retrieval, matched nothing and handed
# off. Found on the live Awash demo.
_SEP = r"[\s,\.!\?;:\-–—፣።፥]*"
_GREETING_ONLY_RE = re.compile(
    rf"^{_SEP}(?:(?:{_GREET_WORD}){_SEP})+$",
    re.IGNORECASE,
)
_GREETING_PREFIX_RE = re.compile(
    rf"^{_SEP}(?:(?:{_GREET_WORD}){_SEP})+",
    re.IGNORECASE,
)

# A name introduction after a greeting is still a greeting, not a question:
# "ሰላም ኦሊ እባላለሁ" ("hello, I'm Oli") is someone saying hello. Deliberately
# limited to explicit name-introduction forms — a bare "I am" would swallow
# "hello, I am looking for a loan", which is a real question.
_INTRODUCTION_RE = re.compile(
    r"\b(my name is|i am called|call me)\b|"
    r"\b(maqaan koo|jedhama|na jedhu)\b|"
    r"\b(magacaygu|waxaa la i yidhaahdaa)\b|"
    r"እባላለሁ|ስሜ|ይበሃል|ስመይ|እባላለው",
    re.IGNORECASE,
)


def strip_greeting(text: str) -> tuple[str, bool]:
    """Split a leading greeting off the rest of the message.

    Returns (remainder, had_greeting). Used both to classify and to search:
    greeting words are content words to BM25, so leaving them in pads a
    query's content-word count and raises the informativeness bar that
    `retrieval.retrieve()` applies — making a greeted question *harder* to
    answer than the same question asked bluntly.
    """
    match = _GREETING_PREFIX_RE.match(text)
    if not match or not match.group(0).strip():
        return text, False
    return text[match.end() :].strip(), True

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

# Deliberately does NOT hardcode a competitor's name or a fixed bank name —
# this classifier is shared across every tenant. The bank-name-agnostic
# alternatives ("than you", "than this bank", "which bank is better") always
# apply; a tenant's own name/slug is spliced in by _comparison_re() below so
# "is Dashen better than CBE" is caught for the CBE tenant without this
# module knowing "CBE" exists.
#
# The differentiator family ("what makes you different", "what sets you
# apart") was added after a live demo: "What makes Awash Bank different from
# other banks in Ethiopia?" fell through to retrieval, matched nothing (no
# bank's own content discusses how it compares to others) and handed off —
# on the single most likely question a bank's own executives ask a sales
# demo. It reads as the assistant being unable to sell its own bank, which
# is the opposite of what the why-choose document exists for.
_COMPARISON_GENERIC = (
    r"\bis .*(better|worse) than (you|this bank)\b|"
    r"\bcompare (you|this bank) (to|with)\b|"
    r"\bwhy (choose|use|pick|should i (choose|use|pick)) you\b|"
    r"\bwhich (bank )?is better\b|"
    r"\bis there a better bank\b|"
    r"\bshould i (switch|move|change) banks?\b|"
    r"\bwhat makes (you|this bank)[^.?!]*\b(different|special|unique|stand out)\b|"
    r"\bwhat sets (you|this bank) apart\b|"
    r"\bhow (are|is) (you|this bank) different\b|"
    r"\bwhy (should i )?bank with (you|this bank)\b"
)


def _comparison_re(bank_aliases: tuple[str, ...]) -> re.Pattern[str]:
    """Comparison-intent pattern for a specific tenant. `bank_aliases` should
    be the names/short forms a customer would actually type (e.g. a bank's
    slug and display name) — matched case-insensitively, literally (no
    partial-word bleed, e.g. "cbe" won't match inside another word)."""
    parts = [_COMPARISON_GENERIC]
    for alias in bank_aliases:
        escaped = re.escape(alias)
        parts.append(
            rf"\bis .*(better|worse) than {escaped}\b|"
            # Bare form deliberately does NOT require a trailing "than X" —
            # "Is CBE better?" asked of the CBE assistant is unambiguous
            # without one, and this still matches "is CBE better than
            # Dashen" too since that's a superset of this same prefix.
            rf"\bis {escaped} (better|worse)\b|"
            rf"\b{escaped} (vs\.?|versus) \w|"
            rf"\bcompare {escaped} (to|with|and)\b|"
            rf"\bwhy (choose|use|pick|should i (choose|use|pick)) {escaped}\b|"
            rf"\bshould i (switch|move|change) (banks? )?to {escaped}\b|"
            # Differentiator phrasings. `[^.?!]*` keeps the gap inside one
            # sentence so a bank name early in a long multi-part message
            # can't reach forward and capture an unrelated "different".
            # These require the tenant's OWN name, so a product question
            # like "what makes Sharik different from a normal account?"
            # stays on the retrieval path where it belongs.
            rf"\bwhat makes {escaped}[^.?!]*\b(different|special|unique|stand out)\b|"
            rf"\bwhat sets {escaped} apart\b|"
            rf"\bhow (is|are) {escaped} different\b|"
            rf"\bwhy (should i )?bank with {escaped}\b|"
            rf"\bwhy {escaped} (over|rather than|instead of)\b|"
            rf"\bdifference between {escaped} and\b"
        )
    return re.compile("|".join(parts), re.IGNORECASE)


def classify_intent(text: str, bank_aliases: tuple[str, ...] = ()) -> str:
    if _GREETING_ONLY_RE.match(text):
        return GREETING

    # A greeting can prefix a real request ("Hello, what are your loan
    # rates?"). Classify what's actually being asked, not the hello — but
    # only after confirming the remainder isn't just an introduction.
    remainder, had_greeting = strip_greeting(text)
    if had_greeting:
        if not remainder or _INTRODUCTION_RE.search(remainder):
            return GREETING
        text = remainder

    if _COMPLAINT_RE.search(text):
        return COMPLAINT
    if _ACCOUNT_RE.search(text):
        return ACCOUNT_SPECIFIC
    if _ADVICE_RE.search(text):
        return INVESTMENT_ADVICE
    if _comparison_re(bank_aliases).search(text):
        return COMPARISON
    return QUESTION


# The auto-answer allowlist, same doctrine as Olink Dispatch: only intents
# named here are answered autonomously; everything else routes to a human
# path or a safety template.
AUTO_ANSWER_INTENTS = frozenset({GREETING, QUESTION, INVESTMENT_ADVICE, COMPARISON})
