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
# Asking for a VALUE only core banking holds — a balance, a transaction, an
# account number, whether a payment landed. We do not have it and will not
# guess it. Refused, and offered a verified teller who does have it.
ACCOUNT_SPECIFIC = "account_specific"
# Asking HOW to do something that happens to involve their account — block a
# lost card, reset a PIN, close an account, see a statement. The answer is on
# every bank's public website and is exactly what this assistant is for.
#
# The split exists because the rule underneath used to key on whether a
# message MENTIONED an account, which is not the question. "What is my
# balance" and "how do I check my balance" both say "my balance"; we cannot
# tell them the number and we absolutely can tell them how to see it.
# Measured on twenty ordinary procedural questions, nine were refused —
# including "my card is lost, what should I do", whose answer was sitting in
# the knowledge base the whole time. A customer whose card has just been
# stolen was getting a lecture about data privacy instead of the number to
# call.
ACCOUNT_PROCEDURE = "account_procedure"
INVESTMENT_ADVICE = "investment_advice"
COMPLAINT = "complaint"
COMPARISON = "comparison"  # "is X better than us?" — answer confidently, never via retrieval
HUMAN_REQUEST = "human_request"  # "let me speak to a person" — not a question at all
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

# The data a customer might ask this assistant to read out. One list, used by
# every rule below, so a new noun cannot be covered by one phrasing and missed
# by another — which is exactly how "give me her account number" slipped past.
_ACCOUNT_NOUN = r"(account|balance|card|statement|loan|pin|password|otp|transaction)"

_ACCOUNT_RE = re.compile(
    # Possessive + account noun, in ANY person. The third-person forms are the
    # important ones and were missing: only "give me her BALANCE" was caught,
    # so "can you give me her account number" — the natural way a person
    # actually asks — was classified as an ordinary question. It then asked
    # the caller for a phone number and filed a content gap telling the bank
    # to write an answer for it.
    rf"\b(my|her|his|their) {_ACCOUNT_NOUN}|"
    r"\b(check|what('| i)?s) my\b|"
    # Disclosure verbs aimed at a person, for any of those nouns rather than
    # balance alone.
    # A possessive NOUN may sit between the pronoun and the account word:
    # "tell me my wife's balance", "send me my brother's statement". Every
    # alternative above breaks on that — "my ... balance" is not adjacent —
    # so the plainest social-engineering phrasing in English was classified
    # as an ordinary question. It was in the very list of five phrasings a
    # reviewer supplied; the Amharic and Oromo translations of it were
    # verified and the English original never was.
    #
    # The disclosure verb stays REQUIRED. Matching "my wife's account" on its
    # own would refuse "I want to transfer money to my wife's account", which
    # is the over-refusal a reviewer had already caught once in Afaan Oromo.
    # Asking to be TOLD something is the whole difference.
    rf"\b(give|tell|send|share|provide) (with |to )?(me|us|her|him|them) "
    rf"((the|her|his|their|my|our) )?(\w+'?s )?{_ACCOUNT_NOUN}\b|"
    r"\bbalance (for|of|on) account\b|"
    r"\boverride (the )?security\b|"
    r"\bባላንስ|ቀሪ ሂሳቤ|ሂሳቤ|ካርዴ|ፒኔ|ሚስጥር ቁጥሬ|"
    r"herrega koo|kaardii koo|xisaabtayda|kaarkayga",
    re.IGNORECASE,
)

# Asking for SOMEONE ELSE's account data in Amharic or Afaan Oromo.
#
# Deliberately a conjunction — an account word AND a third-party marker in the
# same message — rather than the single tokens used for the English rule.
# Native-speaker phrasings make the reason obvious: ንገረኝ ("tell me") and ስጠኝ
# ("give me") open perfectly ordinary questions, and ቁጥሩ ("his number") is
# what you say in "what is the customer service phone number". Matching either
# alone would refuse a large share of legitimate Amharic traffic, and the
# multilingual experience is the thing this product is sold on.
#
# Requiring both keeps "ቁጠባ ሂሳብ እንዴት እከፍታለሁ" (how do I open a savings
# account) answerable while refusing "የ ባንክ ሂሳብ ቁጥሯን ስጠኝ" (give me her bank
# account number).
#
# Phrasings supplied by a native Amharic and Afaan Oromo speaker rather than
# guessed. The Oromo spelling alternation is real: herrega, herreega, heerega
# and hereega all appear.
_OTHERS_ACCOUNT_NOUN = re.compile(
    # ቀሪ ("remaining") is an account word only in combination — see the
    # conjunction below. "ቀሪ ገንዘቧን ላክልኝ" (send me her remaining money) needs
    # it, because that phrasing names no account at all.
    r"ሂሳብ|ሒሳብ|ቁጠባ|ካርድ|ፒን|ሚስጥር ቁጥር|ቀሪ|"
    r"h[ea]+rr?[ea]+ga|kaardii|lakkoofsa herr?[ea]*ga|"
    # "maallaqa hafte" is the Oromo for remaining balance. Matched on its own
    # because the phrasing drops both maallaqa and herrega often enough —
    # "hafte ishee naaf himi" names no account word otherwise. Spelling
    # alternates the same way herrega does: hafte, haftee, haafte, haaftee.
    r"haa?ftee?|"
    # "lakkoofsa dhoksaa" is the Oromo PIN — literally the hidden number.
    # dhoksaa carries it on its own; the number word is spelled at least four
    # ways across supplied phrasings (lakkoofsa, Lakkoofssa, Lakkofssa,
    # Lakkoofsii) and adding it as an account word would also catch phone
    # numbers, which are not account data.
    r"dhoksaa|"
    r"xisaab|akoonto|lambarka akoonka",
    re.IGNORECASE,
)
_OTHERS_POSSESSIVE = re.compile(
    # Amharic: her/his number, her/his account, my wife/spouse (accusative
    # forms are matched by the stem, so ባለቤቴን contains ባለቤቴ).
    r"ቁጥሯ|ቁጥሩ|ሂሳቧ|ሂሳቡ|ባለቤቴ|ሚስቴ|ባለቤቷ|ባለቤቱ|የእሷ|የእሱ|ሚስቱ|ባሏ|"
    # "her/his money". ገንዘቡ is genuinely ambiguous — the -ኡ suffix is both
    # "his" and the definite article, so it also reads as "the money". The
    # conjunction is what makes including it safe: "ገንዘቡን እንዴት እልካለሁ"
    # (how do I send the money) names no account word and stays answerable.
    r"ገንዘቧ|ገንዘቡ|"
    # ቁጥፘ is a keyboard variant of ቁጥሯ ("her number") seen in real input.
    r"ቁጥፘ|"
    # "…forgot it". Not a possessive at all — the third-party signal in
    # "ሚስጥር ቁጥሩን ረሳችው" (she forgot her PIN) is the VERB, and a rule that only
    # looked for possessives missed five of six phrasings of this request.
    #
    # The first-person forms belong here too: "I forgot my PIN" is just as
    # account-specific as "she forgot hers", and both should get the security
    # template rather than an attempt at an answer.
    #
    # Completed past forms only, never the bare stem ረሳ — that would also
    # match the conditional ብረሳ in "what should I do if I forget my PIN",
    # which is a general how-to the bank should answer.
    r"ረሳችው|ረሳች|ረሳው|ረሳሁ|ረስቷል|ረስታለች|ረስተዋል|"
    # Afaan Oromo: her, his, my wife, my husband.
    r"ishee|is?saa|haadha manaa|abbaa manaa|"
    # Somali: her/his, my wife — first pass, still needs a native reviewer.
    r"\bkeeda\b|\bkiisa\b|xaaskayga",
    re.IGNORECASE,
)


# The third thing the rule needs: the speaker asking to BE TOLD, GIVEN or SENT
# something. Without it, a disclosure request and an ordinary transfer look
# identical — both name an account and another person. "ወደ ባለቤቴ ሂሳብ ገንዘብ
# ማስተላለፍ እፈልጋለሁ" (I want to transfer money to my spouse's account) and
# "Maallaqa gara herrega isaa ergu nan danda'aa?" (can I send money to his
# account?) were both refused as security violations.
#
# What separates them is direction: who ends up holding what. Amharic marks it
# with the -ኝ / -ልኝ object suffix on the imperative, Oromo with naa / naaf /
# natti ("to me"), and both with a bare "how much is it".
_DISCLOSURE_INTENT = re.compile(
    r"ስጠኝ|ስጪኝ|ስጡኝ|ንገረኝ|ንገሪኝ|ንገሩኝ|ላክልኝ|ላኪልኝ|ላኩልኝ|አሳየኝ|ስንት ነው|ስንት ናቸው|"
    r"\bnaaf\b|\bnatti\b|\bnaa\b|\bmeeqa\b|\bhimi\b|\bkenni?\b|\bagarsiisi\b",
    re.IGNORECASE,
)

# "…forgot it" is its own complete request — "she forgot her PIN" is asking to
# be told what it is, without ever using a give-me verb. So these satisfy both
# the third-party and the disclosure halves on their own.
_FORGOT = re.compile(r"ረሳችው|ረሳች|ረሳው|ረሳሁ|ረስቷል|ረስታለች|ረስተዋል|"
    # Oromo "forgot" — three unrelated verbs, all in ordinary use:
    # irraanfachuu, dagachuu and walaaluu. Each stem covers the -tte third
    # person and the -dhe first person, and the doubled r in irraanfa is
    # optional because both spellings appear.
    r"\bir?raanfa|\bdaga[td]|\bwalaal")

# "if". Amharic marks the conditional with a ብ- prefix, so matching only
# completed past forms was enough there — ብረሳ never looks like ረሳሁ. Oromo uses
# the same verb form for "I forgot" and "if I forget" and marks the difference
# with a separate word, so it has to be excluded explicitly:
# "dhoksaa koo yoo irraanfadhe maal godha?" (what do I do if I forget my PIN)
# is a how-to the bank should answer, not a request to be told a PIN.
#
# Safe to exclude, because a genuine request that happens to contain "yoo"
# still reaches the three-part rule below: "yoo dandeesse dhoksaa ishee naaf
# himi" (if you can, tell me her PIN) has the noun, the possessive and the
# disclosure marker.
# yoo and yoon are both "if". Missing yoon meant "dhoksaa koo yoon
# irraanfadhe maal godha?" (what do I do if I forget my PIN) was refused —
# the over-refusal direction, which is the one that hurts ordinary customers
# and is invisible from inside the tests.
_CONDITIONAL = re.compile(r"\byoon?\b", re.IGNORECASE)


# ------------------------------------------------- value or procedure?
#
# Everything below decides which side of the account line a message falls on.
# Read the three rules together: procedural markers say "this is a how-to",
# and the other two are vetoes, because a false PROCEDURE is a security
# failure while a false VALUE is only an unnecessary refusal that still
# offers a teller. When they disagree, the refusal wins.

# "How do I…". The marker has to be an actual request for a method, not the
# word "how" anywhere in the sentence — "how much is my balance" is a value
# request wearing a how.
_PROCEDURAL_RE = re.compile(
    r"\bhow (do|can|could|would|should|to) \w*\s*(i|we|you)?\b|"
    r"\bhow (do|does) (it|this|that) work\b|"
    r"\bwhat (should|do|can|must) i do\b|"
    r"\bwhat happens (if|when)\b|"
    r"\bwhat (is|are) the (steps|process|procedure|requirements?)\b|"
    r"\bwhere (do|can) i\b|\bwhen (do|can|should) i\b|"
    r"\b(steps|process|procedure) (to|for)\b|"
    r"\bis it possible to\b|\bam i able to\b|"
    # A bare "can I …" is a how-to in practice: "can I close my account",
    # "can I change my account type". It is not a request to be told a value.
    r"\bcan i \w+\b|"
    # …and the plainest phrasings of an emergency, which almost never arrive
    # with a question word at all: "my card is lost", "someone stole my card",
    # "my card was swallowed by the ATM".
    r"\bmy (card|atm card|debit card) (is|was|got|has been)\b|"
    r"\b(lost|stolen|blocked|swallowed|retained|expired|damaged|not working)\b|"
    r"\bi (forgot|forget|can'?t remember|need to (change|reset|update|block))\b|"
    # Amharic "how" (እንዴት) and "what should I do" (ምን ማድረግ አለብኝ).
    r"እንዴት|ምን ማድረግ|ምን ላድርግ|ብረሳ|ከጠፋ|ቢጠፋ|"
    # Afaan Oromoo. akkamitti/attamitti/akkamiin are unambiguous; the bare
    # "akkam" is a greeting and is deliberately NOT here.
    r"akkamitti|attamitti|akkamiin|maal gochuu|maal godha|yoo .*(bade|banne)|"
    # Tigrinya "how" (ብኸመይ) and Somali "how" (sidee).
    r"ብኸመይ|ከመይ ጌረ|\bsidee\b|\bmaxaan sameeyaa\b",
    re.IGNORECASE,
)

# A request to be told a NUMBER, however politely it is phrased. This vetoes
# the procedural marker, because "how much is my balance" and "show me my last
# five transactions" are core-banking reads with a how-to shape.
#
# "how much" alone is deliberately NOT enough. "How much is the fee on my
# account?" is a tariff question the bank publishes and must keep answering,
# so the pattern requires "how much" to be pointed at the customer's own
# money — "how much is in my", "how much do I owe" — rather than at a price.
_VALUE_ASK_RE = re.compile(
    r"\bhow much (is|are) (in )?(my|the money in my)\b|"
    r"\bhow much (do|does) i(t)? (owe|have|remain)|"
    r"\bhow much do i (owe|have)\b|"
    r"\bhow much money (do i have|is (in|left))\b|"
    r"\bhow many birr (do i|is|are)\b|"
    r"\bwhat('| i)?s my (balance|account number)\b|"
    r"\bwhat is my (balance|account number)\b|"
    r"\b(show|list|display|read out|read me|pull up|look up|tell me|send me) "
    r"(me )?(my|her|his|their)\b|"
    # Somebody else's, asked as an ordinary question. "Can I get my brother's
    # statement" carries no give-me verb, so the disclosure rule below never
    # saw it — and the answer is no regardless of how politely it is asked.
    r"\b(get|see|view|access|obtain|find out|know|check) "
    r"((my|the) )?(\w+'s|her|his|their|someone else'?s) "
    rf"(\w+ ){{0,2}}{_ACCOUNT_NOUN}|"
    # The same request with the possessive after the noun — "the balance of my
    # wife", "the account of my brother". English lets you say it either way
    # and every rule we had only understood one of them, so this phrasing
    # reached retrieval as an ordinary question.
    # "of", never "for". "Open an account FOR my wife" and "a savings account
    # for my daughter" are people buying a product for a relative — the most
    # ordinary traffic a bank has — and an earlier draft of this line refused
    # both of them.
    rf"\b{_ACCOUNT_NOUN}s? (of|belonging to) (my |the )?"
    r"(wife|husband|spouse|brother|sister|mother|father|son|daughter|friend|"
    r"colleague|neighbou?r|client|her|him|them|someone|somebody)\b|"
    # "Did my salary arrive?" — a core-banking read that names no account word
    # at all, which is why it escaped every rule we had.
    r"\b(did|has|have|when did|when will|why (was|were|did))\b[^.?!]{0,40}"
    r"\b(salary|payment|transfer|deposit|pension|remittance|money)\b",
    re.IGNORECASE,
)

# Somebody else's account. A procedural shape must never unlock this: "how do
# I check my wife's balance" is the same request as "tell me my wife's
# balance" with a politer opening.
_THIRD_PARTY_EN = re.compile(
    r"\b(her|his|their|someone|somebody|another person)\b|"
    r"\b(wife|husband|spouse|brother|sister|mother|father|son|daughter|"
    r"friend|colleague|neighbou?r|client)('s)?\b|"
    r"\belse'?s\b",
    re.IGNORECASE,
)

# Facts the bank PUBLISHES, which mention an account only because that is what
# they are about. A daily withdrawal limit, the fee on a transfer, the minimum
# balance, what documents you need — every one of these is on the bank's own
# website, and none of them requires looking anybody up.
#
# Without this, "how much is the fee on my account?" was refused for saying
# "my account", which is the tariff question a bank most wants answered.
_PUBLISHED_FACT_RE = re.compile(
    r"\b(fee|fees|charge|charges|cost|costs|price|tariff|commission|"
    r"rate|rates|interest|limit|limits|minimum|maximum|"
    r"requirements?|documents?|eligibility|criteria|penalty|"
    r"how long|working hours|opening hours)\b|"
    r"ክፍያ|ወለድ|ገደብ|ዝቅተኛ|መስፈርት|"
    r"\bkaffaltii\b|\bdhala\b|\bdaangaa\b",
    re.IGNORECASE,
)


def answerable_without_core_banking(text: str) -> bool:
    """For a message that looks account-related: can we answer it from what
    the bank publishes, or does it need a value only core banking holds?

    Only ever consulted inside the account branch, so its blast radius is that
    branch alone — an ordinary product question never reaches it.

    **The order is the safety property.** The two vetoes run FIRST and are
    absolute; the positive signals cannot override them. Being wrong towards
    the refusal costs a customer one extra step to a verified teller. Being
    wrong the other way is the assistant discussing an account it cannot see,
    which is the whole thing this product promises not to do.
    """
    # Veto 1 — a request to be told a number, however it is dressed up.
    if _VALUE_ASK_RE.search(text):
        return False
    # Veto 2 — somebody else's account. A polite opening is not authority:
    # "how do I check my wife's balance" is "tell me my wife's balance".
    if _THIRD_PARTY_EN.search(text) or asks_for_someone_elses_account(text):
        return False
    # Then, and only then: is this a how-to, or a published fact?
    return bool(_PROCEDURAL_RE.search(text) or _PUBLISHED_FACT_RE.search(text))


def asks_for_someone_elses_account(text: str) -> bool:
    """True when a message asks to be told someone's account data.

    Three things have to line up: an account word, a third-party or ownership
    marker, and the speaker asking to receive something. Two of the three is
    not enough — an ordinary transfer to a relative's account has the first
    two and is a perfectly good question.

    English is handled by _ACCOUNT_RE; this covers the languages where a
    single-token rule would be either useless or far too broad.
    """
    if not _OTHERS_ACCOUNT_NOUN.search(text):
        return False
    if _FORGOT.search(text) and not _CONDITIONAL.search(text):
        return True
    return bool(_OTHERS_POSSESSIVE.search(text) and _DISCLOSURE_INTENT.search(text))


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
    # ተሰረቀ / ተሰርቋል / ሰረቁኝ — "was stolen". Theft is the single most urgent
    # thing a customer can report and the Amharic word for it was absent, so
    # "ገንዘቤ ተሰርቋል" was handled as an ordinary question. My own wording, not a
    # reviewer's: see review/phrasebook.tsv, which marks it as unverified.
    r"ቅሬታ|ተጭበርብሬ|ጠፋብኝ|ማጭበርበር|ተሰረቀ|ተሰርቋ|ሰረቁኝ|ተዘርፍ",
    re.IGNORECASE,
)

# Someone asking to be put through to a person is not asking a question, and
# answering "I don't have verified information about that yet, so I won't
# guess" is a non-sequitur — reported from the live Awash demo on "I need to
# speak to the manager on site". The machinery was already right (a handoff was
# filed and contact details were asked for); only the opening sentence treated
# a request for a human as a gap in the knowledge base.
#
# Checked AFTER the complaint and account rules on purpose. "My money was
# stolen, let me speak to a manager" is a complaint that happens to name the
# remedy, and it must file a complaint handoff; "give me her balance, put me
# through to your manager" must still hit the account guardrail. Escalation is
# the intent only when nothing more specific applies.
_HUMAN_REQUEST_RE = re.compile(
    # An adjective slot between the article and the noun. Without it the
    # article had to sit flush against the noun, so "speak to a LIVE agent" —
    # reported from the deployed demo, and the commonest way an English
    # speaker asks — fell through to an ordinary question and was answered
    # with "I don't have verified information about that yet" plus three
    # unrelated articles. "a person" matched; "a live person" did not.
    #
    # `teller` is in the noun list because this is a bank. Its absence meant
    # "talk to a teller" — the exact words for the feature this product is
    # built around — was not an escalation.
    r"\b(speak|talk|chat) (to|with) (a |an |the |your |someone|somebody)?"
    r"(live |real |actual |human |available )*"
    r"(human|person|manager|supervisor|agent|representative|rep|staff|teller|"
    r"customer (service|care)|real person|someone)|"
    r"\b(connect|transfer|put) me (to|through|with)|"
    r"\b(i (want|need) (to reach )?)?(a|an) (human|real person|actual person)\b|"
    # "live agent", "live teller" as bare phrases — "I need a live agent",
    # "live agent please". The adjective is REQUIRED, deliberately: AGENT
    # BANKING IS A REAL ETHIOPIAN BANKING PRODUCT, so a bare "agent" here
    # would turn "do you have agent banking?" and "where is your nearest
    # agent?" into demands for a manager. Nobody says "live agent" about an
    # agent-banking outlet.
    r"\b(live|real|actual) (agent|person|human|teller|rep|representative|"
    r"operator)\b|"
    # "speak to a LIVE anything". Reported from the demo as "can I speak to a
    # live a gent" — a phone keyboard had split "agent" in two, and the noun
    # list could not match half a word. Chasing individual typos is endless;
    # what carries the meaning here is "live" inside a speak-to construction,
    # whatever noun follows it. Both halves are required, so an ordinary
    # sentence containing "live" — "do you have a live rate feed" — is
    # untouched.
    r"\b(speak|talk|chat) (to|with) (a |an |the )?(live|real|actual)\b|"
    r"\bhuman (agent|being|support)\b|"
    r"\bcall me back\b|"
    # Amharic. "ከ አለቃ ወይም አመራር ጋር መነጋገር እፈልጋለው" was reported from the live
    # demo and matched none of the first pass: አለቃ (boss) and አመራር
    # (management) were missing entirely, and only ማነጋገር was listed, not the
    # equally common መነጋገር.
    #
    # አለቃ, አመራር, ኃላፊ, ሥራ አስኪያጅ, ተቆጣጣሪ and ማኔጀር all stand alone: a native
    # speaker confirmed these are the words a demand for a manager reaches
    # for, and none is a banking product term.
    #
    # ኃላፊ is the one exception, and the exclusion has to be (?!ነ), not the
    # (?!ነት) written first. ኃላፊነት is "responsibility/role" and contains ኃላፊ
    # outright, so a bare match turns "የባንኩ ኃላፊነት ምንድን ነው?" — what is the
    # bank's role — into a demand for a manager. But Ethiopic inflects the
    # FINAL character rather than appending to it, so ኃላፊነቱ is ኃላፊ + ነ + ቱ
    # and contains no "ነት" at all: (?!ነት) let it straight through. Blocking a
    # bare ነ is safe because "ኃላፊ ነው" ("is the head") has a space, which the
    # lookahead sees.
    #
    # The same inflection rule is why several nouns below take a character
    # class on their last letter: አመራር becomes አመራሩ (ር -> ሩ), ማኔጀር becomes
    # ማኔጀሩ, አስኪያጅ becomes አስኪያጁ. Matching the citation form alone missed
    # every one of those — "ከአመራሩ ጋር" classified as an ordinary question.
    # አለቃ, ተቆጣጣሪ and ኃላፊ are unaffected: their suffixes attach after a
    # vowel-final character that does not itself change.
    #
    # An earlier pass also fenced አመራር behind a talk verb, on my own guess
    # that የገንዘብ አመራር would mean "money management". A native speaker
    # corrected it: አመራር is leadership — the people — and the financial sense
    # is አስተዳደር or አያያዝ. The fence cost recall for nothing and is gone.
    r"አለቃ|ተቆጣጣሪ|አመራ[ርሩሪ]|ማኔጀ[ርሩ]|ሥራ አስኪያ[ጅጁ]|ስራ አስኪያ[ጅጁ]|"
    r"ኃላፊ(?!ነ)|ሃላፊ(?!ነ)|ኀላፊ(?!ነ)|"
    r"ሰው\s*(ማነጋገር|መነጋገር|ማውራት|ማግኘት)|ሰው አነጋግሩኝ|ከሰው ጋር|"
    r"ወኪል ጋር|ወኪል ማነጋገር|ደንበኞች አገልግሎት\s*(ማነጋገር|መነጋገር)|"
    # Oromo. "Itti gaafatamaa yookiin bulchaa wajjiin haasa'uu barbaada"
    # matched on itti gaafatamaa alone — bulchaa (administrator) and hoogganaa
    # (leader) were carrying no weight, so the same sentence without the first
    # noun would have missed.
    r"nama waliin|nama dubbisuu|itti gaafatamaa|hoji gaggeessaa|"
    r"\bbulchaa\b|\bhoogganaa\b|\bhogganaa\b|"
    r"qaama namaa|bakka bu'aa|"
    r"qof la hadal|maamule|maareeye",
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
    if (
        _ACCOUNT_RE.search(text)
        or _VALUE_ASK_RE.search(text)
        or asks_for_someone_elses_account(text)
    ):
        # Inside the account branch, and only here, decide which kind it is.
        # `_VALUE_ASK_RE` joins the entry condition as well as the veto: it
        # catches the reads that name no account word at all — "did my salary
        # arrive", "show me my last five transactions" — which used to sail
        # past every rule and reach retrieval as ordinary questions.
        return (
            ACCOUNT_PROCEDURE
            if answerable_without_core_banking(text)
            else ACCOUNT_SPECIFIC
        )
    if _ADVICE_RE.search(text):
        return INVESTMENT_ADVICE
    if _comparison_re(bank_aliases).search(text):
        return COMPARISON
    if _HUMAN_REQUEST_RE.search(text):
        return HUMAN_REQUEST

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
#
# ACCOUNT_PROCEDURE belongs here and ACCOUNT_SPECIFIC never will. The line is
# not "does this touch an account" — it is whether answering needs a value
# only core banking holds. A procedure is published information like any
# other, answered from the bank's own documents with sources attached; a
# value is not ours to know.
AUTO_ANSWER_INTENTS = frozenset({
    GREETING, QUESTION, INVESTMENT_ADVICE, COMPARISON, ACCOUNT_PROCEDURE,
})

# The intents a CURATED ANSWER can actually be served for.
#
# Narrower than the auto-answer allowlist, and the difference is not a
# subtlety — it is the whole reason this constant exists. In `agent.respond`
# the curated-answer lookup sits after the greeting, account, complaint,
# human-request and comparison branches, because a published answer must never
# be able to skip a guardrail. The consequence is that a curated answer for
# any of those intents is unreachable: it would sit in the admin looking
# published and never be sent to anybody.
#
# Found in production. The suggestions list offered "Can I speak to a manager"
# and "My name is Oli" as questions worth answering — one is a request for a
# person and the other is somebody introducing themselves. An operator who
# wrote answers for those would have watched them never appear and concluded
# the feature was broken.
#
# `tests/test_faq.py` asserts this set against what `respond()` actually
# serves, so the two cannot drift apart the way a hand-copied list would.
CURATABLE_INTENTS = frozenset({QUESTION, ACCOUNT_PROCEDURE, INVESTMENT_ADVICE})


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
        # The connectors and verbs that begin the second half of a reply like
        # "Oli Oli and I can be reached at 0911234567". They are what tells
        # _leading_name where the name stops; without them it would swallow
        # the rest of the sentence and _plausible_name would reject the lot,
        # which is how that reply reached an operator with a number and no
        # name attached.
        "and", "or", "but", "you", "i", "im", "can", "could", "be", "is",
        "am", "are", "reach", "reached", "reaching", "contact", "call",
        "phone", "number", "mobile", "cell", "email", "it", "this", "that",
        "we", "us", "they", "them", "so", "if", "then", "also", "for",
    ]
)

# Where the name sits relative to the marker differs by language: English
# and Oromo "maqaan koo" put it after, Amharic/Tigrinya verb forms put it
# before. Both shapes are matched explicitly rather than guessed.
# EXPLICIT introductions — "my name is", "i am called", "call me". These say
# outright that a name follows, so a name of more than one word is safe to
# take, and here it is the normal case rather than an edge one: an Ethiopian
# name is a given name and a father's name, so "My name is Oli Tamrat" is how
# most people introduce themselves.
#
# It was one word. The consequence was not just a missing surname — the
# remainder check below saw "Tamrat" left over, concluded this was not an
# introduction at all, and classified the whole message as a QUESTION. Found
# on the first production list of frequent questions, which was offering
# "My name is Oli" as something for the bank to write an answer to.
_NAME_INTRO_RE = re.compile(
    r"\b(?:my name is|i am called|call me)\s+"
    r"([^\s,.!?።፣]{2,40}(?:\s+[^\s,.!?።፣]{2,40}){0,2})"
    # Must END at a word boundary. Without this a 200-character run of
    # nonsense matches its own first 40 characters, which land inside the
    # plausible-name ceiling and get stored as somebody's name. The old
    # single-word pattern was saved from that by the leftover-text check in
    # `extract_name`, which the explicit forms deliberately skip — so the
    # guard has to be here instead. Caught by a test that already existed.
    r"(?![^\s,.!?።፣])",
    re.IGNORECASE,
)
# The LOOSE forms stay one word and must be the whole remainder — see
# `extract_name`. "I am Oli" introduces; "I am looking for a loan" does not,
# and no amount of wanting full names is worth reading that as one.
_NAME_AFTER_RE = re.compile(
    r"\b(?:this is|i am|i'm|im)\s+([^\s,.!?።፣]{2,40})",
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


def _longest_plausible(candidate: str) -> str | None:
    """The longest leading run of words in `candidate` that reads as a name.

    The multi-word capture is greedy, so "My name is Oli and my number is
    0911234567" hands this "Oli and my". Rejecting the whole thing would lose
    a name that is plainly there — and did, on a test that already existed —
    while accepting it would store "Oli and my" and address the customer that
    way for the rest of the conversation. Shortening from the right gives the
    only reading that is both safe and useful.
    """
    words = candidate.split()
    for take in range(len(words), 0, -1):
        name = _plausible_name(" ".join(words[:take]))
        if name:
            return name
    return None


def extract_name(text: str) -> str | None:
    """Pull a self-introduced name out of a message, or None.

    Only explicit introductions count. Everything captured here is echoed
    back to the customer and persisted on the conversation, so the bar is
    "unmistakably a name" — a false positive would have the assistant
    cheerfully addressing someone as "looking" or, far worse, as their own
    account number.
    """
    for pattern in (
        _NAME_BETWEEN_RE, _NAME_INTRO_RE, _NAME_AFTER_STRICT_RE, _NAME_BEFORE_RE,
    ):
        match = pattern.search(text)
        if match:
            name = _longest_plausible(match.group(1))
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


def _leading_name(text: str) -> str | None:
    """The name at the start of a reply to "may I have your name and number?".

    Only ever called once a valid phone number or email has been found in the
    same message, which is the evidence that this is an answer to that
    question rather than a stray sentence.

    Takes the leading run of name-like words and stops at the first word that
    is not one. The previous rule required the *whole* remainder to be three
    words or fewer, so it captured "Oli 0911234567" but lost the name from
    every natural sentence — "Oli Oli and I can be reached at 0911234567",
    "Abebe Kebede and my phone is 0911234567", "Oli Tamrat, you can reach me
    on 0911234567". Reported from the live CBE demo, where the operator's
    queue got a phone number and no name.

    Stopping at the first non-name word is what keeps this from swallowing a
    sentence: the connectors that open the second clause are in _NOT_A_NAME,
    so the walk ends there. Still capped at _MAX_BARE_NAME_WORDS, and still
    passed through _plausible_name, so nothing reaches it that the stricter
    rule would have accepted.
    """
    words = text.strip(" ,.!?።፣-").split()
    leading: list[str] = []
    for word in words[:_MAX_BARE_NAME_WORDS]:
        if _plausible_name(word) is None:
            break
        leading.append(word)
    if not leading:
        return None
    return _plausible_name(" ".join(leading))


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
        name = _leading_name(stripped)
    return name, contact


_REDACTED = "[contact removed]"


def redact_contact(text: str) -> str:
    """Blank out anything that parses as a phone number or email address.

    Used on aggregate reports — top topics, content gaps — which are the
    artifacts most likely to be exported, pasted into a deck and shown to
    people who never touched the chat. The individual handoff row still
    carries the customer's exact words and their contact fields, because an
    operator returning the call genuinely needs both.

    A customer can volunteer a number unprompted ("call me on 0911234567
    about a loan"), which is an ordinary question and lands in these reports
    on merit. Filtering by how the turn was classified cannot catch that;
    scrubbing the text can.
    """
    out = _EMAIL_RE.sub(_REDACTED, text)
    for match in list(_PHONE_CANDIDATE.finditer(out)):
        if _valid_phone(match.group(0)):
            out = out.replace(match.group(0), _REDACTED)
    return out


def remainder_after_contact(text: str) -> str:
    """The message with any phone number or email address removed.

    Used to decide whether a reply to the contact request also asked
    something. Trailing punctuation survives, because a question mark is the
    signal — a word count misreads "my name is Oli, call me on 0911 234 567"
    as a question about names and calling.
    """
    out = _EMAIL_RE.sub(" ", text)
    for match in list(_PHONE_CANDIDATE.finditer(out)):
        if _valid_phone(match.group(0)):
            out = out.replace(match.group(0), " ")
    return out.strip()
