"""Answers a bank has approved, served without asking a model anything.

The same twenty questions are most of a bank's traffic. Today each one costs a
retrieval, a Gemini call with a 1,500-token budget, and a second or two of the
customer's patience — every time, for an answer that has not changed since the
last person asked it.

The obvious fix is to cache what the model said. This is the better one: turn
the frequent question into an answer the **bank has signed off**, and serve
that.

The difference is not efficiency, it is what the answer IS. A cached model
output is unreviewed text that nobody at the bank has read. A curated answer
is the bank's own words, approved by a named person, with the approval on the
record. When you are selling to a bank, "our compliance team approved this
wording" is the difference between a demo and a deployment — and it happens to
be instant and free as well.

So the loop is: the assistant spots what people keep asking, the bank writes
or edits the answer once, and from then on that question is answered from
their own material with no model in the path at all.

---

**Matching is exact, after normalisation. Deliberately.**

Semantic matching — "close enough question, reuse the answer" — is where a
cache turns into a confidently-wrong answer machine. "What is the fee for
transfers TO CBE" and "FROM CBE" are neighbours in any embedding space and
have different answers. The entire architecture of this product is built to
avoid confident wrongness, and a fuzzy last-mile lookup would reintroduce it
at the one point where nothing downstream can catch it: there is no retrieval
gate, no INSUFFICIENT_CONTEXT, no sources to check. Whatever the FAQ returns
is what the customer reads.

Normalisation therefore does only what cannot change meaning: case, spacing,
surrounding punctuation, and a leading greeting. Not stemming, not stopword
removal, not synonyms. Every one of those merges questions a bank would answer
differently, and the cost of a miss is a normal answer while the cost of a
false hit is the wrong one.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final, NamedTuple

# Punctuation to shed from the ends, including the Ethiopic full stop and
# question mark — a question typed with ። must match the same question typed
# without it, or Amharic gets a worse hit rate than English for punctuation
# reasons alone.
_EDGE: Final = " \t\r\n?!.,;:፣።፥፦'\"“”‘’()[]"

_SPACES: Final[re.Pattern[str]] = re.compile(r"\s+")


def normalise(question: str) -> str:
    """The key a question is stored and looked up under.

    NFKC first, so a question typed with composed and decomposed characters —
    which happens constantly on phone keyboards for Ge'ez — reduces to one
    key rather than two entries nobody can tell apart in the admin.

    Everything here is reversible in meaning: nothing is dropped that could
    make two different questions collide. See the module docstring for why
    that restraint is the point rather than a limitation.
    """
    text = unicodedata.normalize("NFKC", question)
    text = _SPACES.sub(" ", text).strip().strip(_EDGE).strip()
    return text.casefold()


def key(question: str, language: str) -> str:
    """The full lookup key: a question is only the same question in the same
    language.

    "Balance" means one thing in an English question and is a Somali word in
    another; more practically, a bank writes a different answer for each
    language and storing them under one key would make publishing the Amharic
    version silently overwrite the English one.
    """
    return f"{language}\x1f{normalise(question)}"


def matches(stored_question: str, stored_language: str,
            asked: str, asked_language: str) -> bool:
    """Whether an approved answer applies to what was just asked.

    A function rather than a comparison at the call site, so there is exactly
    one definition of "the same question" in the system and a test can pin it.
    """
    return key(stored_question, stored_language) == key(asked, asked_language)


# ------------------------------------------------- reading a published FAQ
#
# A bank's FAQ page is the single best content it owns, and the only one that
# arrives in exactly the shape this table wants: somebody has already decided
# which questions matter and written the approved answer to each. Typing them
# back in one at a time is the reason a bank with forty published answers ends
# up with four curated.

# The question mark, Latin and Ethiopic. A line that ends in one is a question
# in every language this product serves.
_ASKS: Final[re.Pattern[str]] = re.compile(r"[?？፧]\s*$")

# The other shape: an explicit label. Covers FAQ pages whose questions are
# statements ("Account activation") and would otherwise be invisible, and
# survives a copy from a PDF where the layout is gone.
_Q_LABEL: Final[re.Pattern[str]] = re.compile(r"^\s*(?:q|question)\s*[:.)-]\s*", re.I)
_A_LABEL: Final[re.Pattern[str]] = re.compile(r"^\s*(?:a|ans|answer)\s*[:.)-]\s*", re.I)

# `Faq.question` is String(400). A "question" longer than that is a paragraph
# that happened to end in a question mark, and importing it would create a key
# no customer will ever type.
MAX_QUESTION = 400


class QAPair(NamedTuple):
    question: str
    answer: str


# A printed page marker, and the browser's date/time stamp beside it. Both are
# injected at every page boundary when somebody prints a web page to PDF, which
# is the realistic way an FAQ reaches us: the site blocks fetching, and a PDF
# survives being emailed from a phone.
_PAGE_MARK: Final[re.Pattern[str]] = re.compile(
    r"^\s*page\s+\d+\s+of\s+\d+\s*$", re.I
)
_STAMP: Final[re.Pattern[str]] = re.compile(
    r"^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s*\d{1,2}:\d{2}\s*[\u202f\s]*[ap]\.?m\.?\s*$", re.I
)
_BARE_EMAIL: Final[re.Pattern[str]] = re.compile(r"^\s*[^\s@]+@[^\s@]+\.[^\s@]+\s*$")
_MENU: Final[re.Pattern[str]] = re.compile(r"^\s*(?:menu|home|contact us)\s*$", re.I)

# Ends a sentence in any language this product serves. A repeated line that
# ends a sentence is an answer somebody gave twice; one that does not is a
# label, and labels repeated down a document are furniture.
_SENTENCE_END: Final[re.Pattern[str]] = re.compile(r"[.!?።፧:]\s*$")

# How many times a label has to recur before it is furniture rather than
# coincidence. Five is past what a real answer repeats and well under the page
# count of any FAQ worth importing.
_FURNITURE_REPEATS = 5


def strip_page_furniture(text: str) -> str:
    """Drop the header, footer and page markers a printed page carries.

    Found the first time a real bank FAQ went through this: 18% of the pairs
    came out with `Menu … info@… 8/10/26, 9:36 AM Page 3 of 34` sitting inside
    the answer. That text is then served to a customer **verbatim**, because a
    curated answer has no retrieval gate and no sources for anyone to check.

    This is not the same problem `ingest.py` solves. There, navigation sits at
    the edges of one HTML document and is sliced away with the first and last
    section. Here it is re-injected at every page boundary, in the middle of
    the answer it interrupts, so position says nothing and only shape does.
    """
    lines = text.splitlines()
    counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if stripped:
            counts[stripped] = counts.get(stripped, 0) + 1

    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _PAGE_MARK.match(stripped) or _STAMP.match(stripped):
            continue
        if _BARE_EMAIL.match(stripped) or _MENU.match(stripped):
            continue
        if (
            counts.get(stripped, 0) >= _FURNITURE_REPEATS
            and not _SENTENCE_END.search(stripped)
            and len(stripped) <= 80
        ):
            continue
        kept.append(line)
    return "\n".join(kept)


# A line that starts like a question. Used only to rejoin a question the page
# broke across two lines — never to decide that something IS a question.
_OPENS_A_QUESTION: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:what|how|why|who|when|where|which|is|are|can|could|do|does|did|"
    r"will|would|should|may|must)\b",
    re.I,
)


def _clean(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip()


def pairs(text: str) -> list[QAPair]:
    """Question/answer pairs from a copied FAQ page.

    Two signals, and no others:

    - a line ending in a question mark, Latin or Ethiopic;
    - a line explicitly labelled `Q:` / `Question:`.

    Everything from there until the next question is that question's answer.

    **Under-detection is the correct failure.** A looser rule — treating short
    lines or title-case lines as questions — would turn body text and headings
    into curated answers, and curated answers are the one path with nothing
    downstream to catch a mistake: no retrieval gate, no INSUFFICIENT_CONTEXT,
    no sources for anyone to check. Whatever this produces is what a customer
    reads. A question this misses costs somebody typing one entry by hand; a
    question this invents costs the bank's credibility, so the rule stays
    strict and the preview exists to catch the rest.

    Pairs arrive with no status of their own — the caller stores them as
    drafts, because an import has nobody's name on it and `approved_by` is the
    entire difference between a curated answer and a cache.
    """
    found: list[QAPair] = []
    question: str | None = None
    answer: list[str] = []

    for raw in strip_page_furniture(text).splitlines():
        line = raw.strip()
        if not line:
            if answer:
                answer.append("")
            continue

        labelled = bool(_Q_LABEL.match(line))
        stripped = _Q_LABEL.sub("", line).strip() if labelled else line
        is_question = (labelled or bool(_ASKS.search(line))) and len(
            stripped
        ) <= MAX_QUESTION

        if is_question:
            # A long question wrapped across two lines arrives as a fragment
            # ending in the question mark — "earn?" instead of "Are there
            # limits to how many coins I can earn?". Rejoin it, but only when
            # the line above opens like a question and was left unfinished;
            # anything looser would weld the tail of an answer onto the front
            # of the next question.
            if answer:
                above = answer[-1].strip()
                if (
                    above
                    and _OPENS_A_QUESTION.match(above)
                    and not _SENTENCE_END.search(above)
                ):
                    stripped = f"{above} {stripped}".strip()
                    answer.pop()
            if question is not None and _clean(answer):
                found.append(QAPair(question, _clean(answer)))
            question, answer = stripped, []
            continue

        if question is not None:
            answer.append(_A_LABEL.sub("", line) if _A_LABEL.match(line) else line)

    if question is not None and _clean(answer):
        found.append(QAPair(question, _clean(answer)))

    # Two entries under one key is a database error at write time and a race
    # over which answer a customer sees. Keep the first: a well-built FAQ page
    # answers a question where it is asked, and repeats it later under a
    # heading like "See also".
    seen: set[str] = set()
    unique: list[QAPair] = []
    for pair in found:
        k = normalise(pair.question)
        if k in seen:
            continue
        seen.add(k)
        unique.append(pair)
    return unique
