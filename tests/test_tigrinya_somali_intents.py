"""Tigrinya and Somali reach the guardrails at all.

The classifier is the SOLE gate — there is no LLM re-classification above it —
so an intent it misses is a control that never runs. Filling in the Tigrinya
and Somali rows of the phrasebook and running them showed 21 of 30 failing,
and every one of the 21 was ti or so: English, Amharic and Afaan Oromo passed
completely.

The cause is that the two Ge'ez languages are not one language. Amharic writes
the account as ሂሳብ and management as አመራር; Tigrinya writes ሕሳብ and ኣመራር, with
different characters for the same sounds. Every Amharic keyword in this module
matched exactly none of it. Somali had four account words and no verb for
speaking to a person.

What that cost, concretely: a Tigrinya customer reporting theft filed no
complaint and reached nobody; one asking for a manager was answered as though
they had asked a question about products; one asking for someone else's
balance was never met by the account-data refusal. No data could leak — the
assistant holds none — but the refusal that explains why is a control, and it
was not running.

The second half of this file is the direction that is harder to see. Over-
refusal is its own failure: a real customer gets stonewalled and nothing
records it as wrong. Widening the rules to catch the above broke "Waa maxay
xisaabta kaydsashada?" — what IS a savings account — into a security refusal,
because "waa maxay" is simply "what is" and had been added as a disclosure
marker. That is pinned below so it cannot come back.
"""

from __future__ import annotations

import pytest

from bankassist import classifier

# --------------------------------------------------------- must be caught

CAUGHT = [
    # (text, expected intent, what it means)
    ("ምስ ሓላፊ ክዛረብ እደሊ", classifier.HUMAN_REQUEST, "ti: speak to a manager"),
    ("ምስ ኣካያዲ ክዛረብ እደሊ", classifier.HUMAN_REQUEST, "ti: speak to a manager (ኣካያዲ)"),
    ("ኣካያዲኡ ክዛረበኒ", classifier.HUMAN_REQUEST, "ti: inflected ኣካያዲ -> ኣካያዲኡ"),
    ("ሰብ ኣዘራርቡኒ", classifier.HUMAN_REQUEST, "ti: a second verb for the same ask"),
    ("Waxaan rabaa inaan la hadlo maamulaha", classifier.HUMAN_REQUEST, "so: speak to a manager"),
    ("Qof ha ila hadlo", classifier.HUMAN_REQUEST, "so: let a person speak to me"),
    ("Waxaan doonayaa inaan arko madaxa", classifier.HUMAN_REQUEST, "so: see the head"),
    ("ቁጽሪ ሕሳባ ሃበኒ", classifier.ACCOUNT_SPECIFIC, "ti: give me HER account number"),
    ("ናይ በዓልቲ ቤተይ ሚዛን ንገረኒ", classifier.ACCOUNT_SPECIFIC, "ti: my wife's balance"),
    ("ሚዛና ስደደለይ", classifier.ACCOUNT_SPECIFIC, "ti: send me her balance"),
    ("ፒን ኮዳ ረሲዓቶ፣ እንታይ እዩ?", classifier.ACCOUNT_SPECIFIC, "ti: she forgot her PIN"),
    ("I sii lambarka xisaabteeda", classifier.ACCOUNT_SPECIFIC, "so: give me her account number"),
    ("Waxay iloowday PIN-keeda, waa maxay?", classifier.ACCOUNT_SPECIFIC, "so: she forgot her PIN"),
    ("ገንዘበይ ተሰሪቑ", classifier.COMPLAINT, "ti: my money was stolen"),
    ("ገንዘበይ ጠፊኡ", classifier.COMPLAINT, "ti: my money is gone"),
    ("Lacagtayda waa la xaday", classifier.COMPLAINT, "so: my money was stolen"),
]


@pytest.mark.parametrize("text,expected,meaning", CAUGHT, ids=[c[2] for c in CAUGHT])
def test_the_guardrail_fires(text: str, expected: str, meaning: str) -> None:
    got = classifier.classify_intent(text)
    assert got == expected, f"{meaning}: expected {expected}, got {got}"


# ------------------------------------------------------ must NOT be caught

ORDINARY = [
    # The trap in each language: a word that shares a root with "manager".
    ("ሓላፍነት ባንኪ እንታይ እዩ?", "ti: what is the bank's RESPONSIBILITY"),
    ("Waa maxay mas'uuliyadda bangiga?", "so: what is the bank's responsibility"),
    # "What is X" — the commonest opening in both languages, and the one that
    # a disclosure marker must never be built out of.
    ("Waa maxay xisaabta kaydsashada?", "so: what IS a savings account"),
    ("Waa maxay xisaab jaari ah?", "so: what is a current account"),
    ("Waa maxay faa'iidada xisaabta?", "so: what is the benefit of the account"),
    ("ናይ ቁጠባ ሕሳብ እንታይ እዩ?", "ti: what IS a savings account"),
    # Rates and procedures, which are published facts.
    ("Waa immisa ribaadu?", "so: what is the interest rate"),
    ("ወለድ ክንደይ እዩ?", "ti: what is the interest rate"),
    ("ክንደይ ወለድ ኣለዎ?", "ti: how much interest does it carry"),
    ("ከመይ ጌረ ናይ ቁጠባ ሕሳብ እኸፍት?", "ti: how do I open a savings account"),
    ("Sidee baan u furaa xisaab kaydsasho ah?", "so: how do I open a savings account"),
    ("ካርድ ብኸመይ እሓድስ?", "ti: how do I renew a card"),
    ("ናይ ባንኪ ሰዓታት እንታይ እዩ?", "ti: what are the bank's hours"),
]

# A customer asking about their OWN account procedure is answerable, so both
# of these count as "not refused".
FINE = {classifier.QUESTION, classifier.ACCOUNT_PROCEDURE}


@pytest.mark.parametrize("text,meaning", ORDINARY, ids=[c[1] for c in ORDINARY])
def test_an_ordinary_question_is_not_refused(text: str, meaning: str) -> None:
    got = classifier.classify_intent(text)
    assert got in FINE, (
        f"{meaning}: over-refused as {got}. A stonewalled customer is a "
        "failure nobody can see from inside the product."
    )


def test_the_disclosure_markers_are_not_bare_question_words() -> None:
    """The specific regression, named.

    "waa maxay" (so) and "ክንደይ እዩ" (ti) both mean "what/how much is it" and
    both were added as disclosure markers while widening these rules. Either
    one turns every ordinary product question in that language into a
    security refusal.
    """
    pattern = classifier._DISCLOSURE_INTENT.pattern
    assert "waa maxay" not in pattern
    assert "ክንደይ እዩ" not in pattern
    # And the markers that should be there still are.
    assert "i sii" in pattern and "ንገረኒ" in pattern


def test_amharic_spellings_do_not_stand_in_for_tigrinya() -> None:
    """The root cause, pinned. Both languages use Ge'ez and they are not
    interchangeable: ሂሳብ is the Amharic account, ሕሳብ the Tigrinya one. If the
    Tigrinya forms disappear from the rules, so does every control above."""
    from pathlib import Path

    src = Path("bankassist/classifier.py").read_text(encoding="utf-8")
    for tigrinya in ("ሕሳብ", "ኣካያዲ", "ተሰሪቑ", "ሚዛን"):
        assert tigrinya in src, f"the Tigrinya {tigrinya} is gone from the rules"
