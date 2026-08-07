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

# Deliberately excludes ultra-short tokens (fi, nu, ee, ku, la) — they
# collide across languages and with English, and a wrong positive here now
# costs more than a miss, because unmarked Latin text falls through to
# English by elimination below.
_OROMO_WORDS = {
    "akkam", "maaloo", "baankii", "herrega", "herreega", "maallaqa", "liqii",
    "kaffaltii", "tajaajila", "waan", "akkamitti", "danda", "qaba", "kootii",
    "koo", "banuu", "guyyaa", "hangam",
    "waa'ee", "waee", "beekuu", "barbaada", "barbaade", "barbaadha",
    "maqaan", "maqaa", "eenyu", "maaliif", "eessa", "yoom", "keessan",
    "keessa", "irratti", "irraa", "waliin", "jedhama", "jirta", "jirtu",
    "jirtan", "galatoomi", "nagaa", "argachuu", "fayyadamuu", "banachuu",
    "kaffaluu", "yookaan", "immoo", "garuu", "dhiyeessuu", "hojjechuu",
}
_SOMALI_WORDS = {
    "waan", "waxaan", "lacag", "lacagta", "bangiga", "bangi", "xisaab",
    "xisaabta", "sidee", "fadlan", "furaa", "furo", "maxay", "immisa",
    "adeegga", "kaarka",
    "waxa", "saabsan", "goorma", "xagee", "doonayaa", "rabaa", "ogaan",
    "mahadsanid", "magacaygu", "aniga", "adiga", "annaga", "iyaga",
    "maxaa", "deynta", "amaahda", "macmiilka", "warqad",
}
# How many unmarked Latin words before a message counts as English prose.
_LATIN_PROSE_WORDS = 3

_ENGLISH_WORDS = {
    "the", "how", "what", "is", "my", "account", "open", "can", "i", "to",
    "loan", "deposit", "rate", "card", "bank", "money", "tell", "me", "more",
    "about", "your", "you", "do", "does", "are", "where", "when", "why",
    "which", "for", "with", "and", "need", "want", "have", "get", "send",
    "transfer", "branch", "fee", "fees", "savings", "interest", "there",
    "this", "that", "would", "should", "could", "please", "of", "in", "on",
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
        # No positive marker at all. Among the five supported languages only
        # English, Afaan Oromo and Somali use Latin script, so unmarked Latin
        # prose is English by elimination. Without this, an English question
        # containing none of the listed words returned None, the sticky
        # conversation language won, and someone who had greeted in Amharic
        # got Amharic scaffolding wrapped around an English answer.
        #
        # The word-count floor keeps that from overcorrecting: a bare "ATM"
        # or "OK" mid-Amharic-conversation carries no real signal and must
        # not flip the language.
        return "en" if len(words) >= _LATIN_PROSE_WORDS else None
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
    r"akkam|akam|asham\w*|jirta|jirtu|jirtan|fayyaa|there|"
    r"dehna|dehina|nagaadha|iska warran|sidee tahay|subax wanaagsan|"
    r"ሰላም|ሰላምታ|ጤና ይስጥልኝ|ደህና|ደሕና|ነህ|ነሽ|ነኝ|ኖት|ናችሁ|ኑ|ከመይ|ሓዲኹም|"
    r"እንደምን|አደርክ|አደርሽ|አደራችሁ|ዋልክ|ዋልሽ|አለህ|አለሽ|አላችሁ"
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

    # An introduction with no request attached is someone saying hello —
    # "I am Oli", "ኦሊ ነኝ". Checked last so a real request always wins:
    # "I am Oli, what are your rates?" never reaches here, because
    # extract_name() only accepts a bare introduction as the whole message.
    if extract_name(text) is not None:
        return GREETING

    return QUESTION


# The auto-answer allowlist, same doctrine as Olink Dispatch: only intents
# named here are answered autonomously; everything else routes to a human
# path or a safety template.
AUTO_ANSWER_INTENTS = frozenset({GREETING, QUESTION, INVESTMENT_ADVICE, COMPARISON})


# --------------------------------------------------------------- name

# Continuations that make "I am ..." a statement of need rather than an
# introduction. Without this, "Hi, I am looking for a loan" would be read
# as someone named "looking".
_NOT_A_NAME = frozenset(
    [
        "looking", "interested", "new", "here", "sorry", "confused", "trying",
        "wondering", "calling", "asking", "having", "unable", "not", "a", "an",
        "the", "just", "still", "already", "planning", "hoping", "worried",
        "customer", "client", "student", "unemployed", "employed", "retired",
        # Prepositions and fillers that sit exactly where a name would in
        # "call me on 0911234567" or "this is about my loan" — telephony and
        # topic phrasing, not an introduction. These matter most on the
        # contact-capture turn, where the customer is replying to a direct
        # question and short answers are the norm.
        "on", "at", "in", "about", "regarding", "me", "my", "your", "yes",
        "no", "ok", "okay", "please", "thanks", "thank", "sure", "hello",
    ]
)

# Where the name sits relative to the marker differs by language: English
# and Oromo "maqaan koo" put it after, Amharic/Tigrinya verb forms put it
# before. Both shapes are matched explicitly rather than guessed.
_NAME_AFTER_RE = re.compile(
    r"\b(?:my name is|i am called|call me|this is|i am|i'm|im)\s+([^\s,.!?።፣]{2,40})",
    re.IGNORECASE,
)
_NAME_AFTER_STRICT_RE = re.compile(
    r"\b(?:maqaan koo|maqaan kiyya|magacaygu waa|magacaygu)\s+([^\s,.!?።፣]{2,40})",
    re.IGNORECASE,
)
_NAME_BEFORE_RE = re.compile(
    r"([^\s,.!?።፣]{2,40})\s+(?:እባላለሁ|እባላለው|ይበሃል|ነኝ|እየ|jedhama|jedhamaa)",
    re.IGNORECASE,
)
_NAME_BETWEEN_RE = re.compile(
    r"(?:ስሜ|ስመይ)\s+([^\s,.!?።፣]{2,40})(?:\s+(?:ነው|እዩ))?",
    re.IGNORECASE,
)


def _plausible_name(candidate: str) -> str | None:
    """Reject anything that is obviously not a person's name."""
    name = candidate.strip(" ,.!?።፣'\"")
    if not (2 <= len(name) <= 40):
        return None
    lowered = name.lower()
    # Per word, not per phrase. A multi-word candidate is only a name if every
    # word is name-like: "call me on" survived a whole-string check and was
    # stored as somebody's name.
    if any(word in _NOT_A_NAME for word in lowered.split()):
        return None
    # A greeting word sitting where a name should be means the pattern
    # matched the greeting itself — "ሰላም ነኝ" is "I'm well", not a name.
    if _GREETING_ONLY_RE.match(name):
        return None
    # Digits are never part of a name here, and an account number captured
    # as one would be stored and echoed back — exactly what must not happen.
    if any(ch.isdigit() for ch in name):
        return None
    return name


def extract_name(text: str) -> str | None:
    """Pull a self-introduced name out of a message, or None.

    Only explicit introductions count. Everything captured here is echoed
    back to the customer and persisted on the conversation, so the bar is
    "unmistakably a name" — a false positive would have the assistant
    cheerfully addressing someone as "looking" or, far worse, as their own
    account number.
    """
    for pattern in (_NAME_BETWEEN_RE, _NAME_AFTER_STRICT_RE, _NAME_BEFORE_RE):
        match = pattern.search(text)
        if match:
            name = _plausible_name(match.group(1))
            if name:
                return name

    # Bare "I am X" is the loosest form, so it only counts when X is the
    # whole remainder — "I am Oli" introduces, "I am looking for a loan"
    # does not.
    remainder, _had = strip_greeting(text)
    match = _NAME_AFTER_RE.search(remainder)
    if match:
        tail = remainder[match.start() :]
        after = tail[match.end() - match.start() :].strip(" ,.!?።፣")
        if not after or after.lower().startswith(("nice to meet", "ደስ")):
            return _plausible_name(match.group(1))
    return None


# ---------------------------------------------------------------- contact

# Phone numbers are matched by finding digit runs and then *validating* them,
# rather than by one regex that has to anticipate every way a person spaces a
# number. "0911234567", "0911 234 567" and "+251 91 123 4567" are the same
# number and all three reach an operator; a pattern strict enough to be safe
# was not forgiving enough to be useful.
_PHONE_CANDIDATE = re.compile(r"\+?\d[\d\s.\-()]{6,20}\d")
_EMAIL_RE = re.compile(r"[^\s@,;]+@[^\s@,;]+\.[a-z]{2,}", re.IGNORECASE)

# In the awaiting-contact turn a bare name is expected ("Oli", "Oli Tamrat"),
# so extract_name's requirement of an explicit introduction is too strict.
_MAX_BARE_NAME_WORDS = 3


def normalize_phone(raw: str) -> str:
    """Strip formatting so two spellings of one number compare equal."""
    cleaned = re.sub(r"[\s.\-()]", "", raw)
    return cleaned


def _valid_phone(raw: str) -> str | None:
    """Accept a digit run only if it is shaped like a reachable number.

    Deliberately narrow on the local forms, because the thing that must never
    be captured here is an account number. Ethiopian mobiles are 09/07 plus
    eight digits, or +251 with the same; CBE account numbers are thirteen
    digits starting with 1, so they match none of these rules. Anything else
    has to carry an explicit country code, which an account number never does.
    """
    cleaned = normalize_phone(raw)
    plus = cleaned.startswith("+")
    digits = cleaned.lstrip("+")
    if not digits.isdigit():
        return None
    if digits.startswith("251") and len(digits) == 12 and digits[3] in "97":
        return "+" + digits
    if digits.startswith("0") and len(digits) == 10 and digits[1] in "97":
        return digits
    if plus and 8 <= len(digits) <= 15:
        return "+" + digits
    return None


def extract_contact(text: str) -> tuple[str | None, str | None]:
    """Pull (name, phone-or-email) out of a reply to the contact request.

    Only ever called when the assistant has just asked for these, which is
    what makes the looser name rule safe: an unprompted message is still
    handled by extract_name's strict introduction patterns.

    Returns (None, None) when the customer replied with something else
    entirely. That is a normal outcome, not an error — they changed the
    subject, and the caller answers the message instead of asking again.
    """
    email = _EMAIL_RE.search(text)
    contact: str | None = email.group(0) if email else None

    consumed: list[str] = [email.group(0)] if email else []
    if contact is None:
        for match in _PHONE_CANDIDATE.finditer(text):
            valid = _valid_phone(match.group(0))
            if valid:
                contact = valid
                consumed.append(match.group(0))
                break

    # Look for the name in what is left once the contact details are removed,
    # so "Oli 0911234567" yields "Oli" rather than a string containing digits.
    remainder = text
    for piece in consumed:
        remainder = remainder.replace(piece, " ")

    name = extract_name(remainder) or extract_name(text)

    # Both looser rules below require contact details in the same message.
    # Without that guard a customer answering "yes" gets stored as being named
    # "yes" and addressed that way for the rest of the chat, and a blocklist of
    # filler words would have to be right in five languages. Tying them to a
    # number found alongside costs nothing real: a name with no way to call it
    # is not actionable for an operator anyway.
    if name is None and contact is not None:
        # An explicit introduction carrying trailing text — "my name is Oli,
        # call me on 0911234567". extract_name rejects that shape on purpose,
        # because unprompted "I am looking for a loan" must not read as a
        # name. Here the valid number is the evidence that the customer is
        # answering the question we just asked.
        intro = _NAME_AFTER_RE.search(remainder)
        if intro:
            name = _plausible_name(intro.group(1))
    if name is None and contact is not None:
        stripped, _greeted = strip_greeting(remainder)
        candidate = stripped.strip(" ,.!?።፣-")
        if candidate and len(candidate.split()) <= _MAX_BARE_NAME_WORDS:
            name = _plausible_name(candidate)
    return name, contact
