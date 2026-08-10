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
from typing import Final

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
