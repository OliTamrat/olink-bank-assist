"""Asking for a person is not asking a question.

Reported from the live Awash demo: "I need to speak to the manager on site"
was answered with "I don't have verified information about that yet, so I
won't guess." The machinery underneath was already correct — a handoff was
filed and contact details were asked for — but the opening sentence treated a
request for a human as a gap in the knowledge base, which is a non-sequitur.

The ordering tests matter more than the happy path. Escalation must never
outrank a complaint or the account guardrail: "my money was stolen, let me
speak to a manager" is a complaint that happens to name its own remedy, and
"give me her balance, put me through to your manager" is still an attempt to
get someone else's account details.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import classifier
from bankassist.i18n import t
from bankassist.models import Handoff


def _ask(client: TestClient, message: str) -> dict[str, Any]:
    resp = client.post("/chat/demo", json={"message": message})
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


@pytest.mark.parametrize("message", [
    "I need to speak to the manager on site",
    "Can I talk to a human?",
    "I want to speak with customer service",
    "connect me to an agent",
    "Put me through to a representative please",
    "ሰው ማነጋገር እፈልጋለሁ",
    "Nama waliin dubbachuu barbaada",
])
def test_a_request_for_a_person_is_not_treated_as_a_knowledge_gap(
    client: TestClient, demo_bank: Any, message: str
) -> None:
    data = _ask(client, message)
    assert data["intent"] == "human_request", message
    assert t(data["language"], "human_request_ack") in data["reply"]
    # The exact sentence the customer saw instead, and the reason this exists.
    assert t(data["language"], "unknown") not in data["reply"]
    assert data["handoff_created"] is True


def test_it_still_collects_a_way_to_reach_them(
    client: TestClient, demo_bank: Any
) -> None:
    """Routing to a person that nobody can call is not routing to a person."""
    data = _ask(client, "I need to speak to the manager on site")
    assert data["awaiting_contact"] is True
    assert data["reply"].rstrip().endswith(t(data["language"], "ask_contact"))


def test_the_handoff_says_why(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """A bank should be able to tell people who are unhappy from people who
    simply want a human — same queue, different reason."""
    _ask(client, "Can I talk to a human?")
    reasons = db_session.execute(select(Handoff.reason)).scalars().all()
    assert reasons == ["human_requested"]


@pytest.mark.parametrize("message,expected", [
    # A complaint that names its own remedy is still a complaint.
    ("My money was stolen, let me speak to a manager", "complaint"),
    # And the account guardrail outranks both.
    ("Give me her account balance, put me through to your manager",
     "account_specific"),
])
def test_escalation_never_outranks_a_more_specific_intent(
    client: TestClient, demo_bank: Any, message: str, expected: str
) -> None:
    assert _ask(client, message)["intent"] == expected, message


def test_it_is_not_on_the_auto_answer_allowlist(
    client: TestClient, demo_bank: Any
) -> None:
    """Escalation goes to the human path by definition. If it ever joins the
    allowlist, the assistant is answering the one thing it was told not to."""
    assert classifier.HUMAN_REQUEST not in classifier.AUTO_ANSWER_INTENTS


def test_an_ordinary_question_is_untouched(
    client: TestClient, demo_bank: Any
) -> None:
    """The pattern is broad enough to be worth a false-positive check: nothing
    about opening an account mentions wanting a person."""
    assert _ask(client, "How do I open a savings account?")["intent"] == "question"


def test_it_survives_being_asked_while_awaiting_contact(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """The bug class the guardrail matrix exists for, and one this intent
    walked straight into when it was added.

    Mid-way through being asked for a phone number, contact capture runs
    before intent classification and returns early for anything not on the
    guarded list. A new human-path intent that isn't on that list gets
    swallowed: the number is stored, the customer is thanked, and their
    request to speak to someone files no handoff at all.
    """
    first = _ask(client, "Do you sponsor competitive cheese rolling tournaments?")
    assert first["awaiting_contact"] is True

    resp = client.post("/chat/demo", json={
        "message": "Oli 0911234567, and I need to speak to a manager",
        "conversation_id": first["conversation_id"],
    })
    data = resp.json()
    assert data["intent"] == "human_request"
    reasons = db_session.execute(select(Handoff.reason)).scalars().all()
    assert "human_requested" in reasons, "the escalation was swallowed by contact capture"


# --------------------------------------------- escalation beyond English


@pytest.mark.parametrize("message", [
    # Reported verbatim from the live CBE demo. Matched none of the first
    # pass: አለቃ (boss) and አመራር (management) were absent, and only ማነጋገር was
    # listed, not the equally common መነጋገር.
    "ከ አለቃ ወይም አመራር ጋር መነጋገር እፈልጋለው",
    "ከአለቃው ጋር መነጋገር እፈልጋለሁ",
    "ሰው መነጋገር እፈልጋለሁ",
    "ተቆጣጣሪውን ማነጋገር እችላለሁ?",
    "ኃላፊውን ማነጋገር እፈልጋለሁ",
    # Oromo: the reported sentence matched on itti gaafatamaa alone, so the
    # other two nouns in it were carrying no weight of their own.
    "Bulchaa wajjiin haasa'uu barbaada",
    "Hoogganaa wajjiin dubbachuu barbaada",
])
def test_escalation_is_recognised_in_amharic_and_oromo(
    client: TestClient, demo_bank: Any, message: str
) -> None:
    assert _ask(client, message)["intent"] == "human_request", message


@pytest.mark.parametrize("message", [
    # ኃላፊነት is "responsibility/role" — ኃላፊ ("head") sits inside it, so a bare
    # match turns a question about what the bank is responsible for into a
    # demand for a manager. The inflected forms are covered separately below,
    # since they are what broke the first version of the guard.
    "የባንኩ ኃላፊነት ምንድን ነው?",
    # "የገንዘብ አመራር ምክር ይስጡኝ" used to sit here, on my assumption that አመራር
    # could mean "money management" and therefore needed a talk verb beside
    # it. A native speaker corrected the premise: አመራር is leadership — the
    # people — and the financial sense is አስተዳደር or አያያዝ. The case was
    # guarding a sentence nobody would write, and the fence it justified cost
    # real recall on the phrasings people do.
    "የቁጠባ ሂሳብ እንዴት እከፍታለሁ?",
    "የብድር ወለድ ስንት ነው?",
])
def test_ordinary_amharic_questions_are_not_escalation(
    client: TestClient, demo_bank: Any, message: str
) -> None:
    """Over-refusal is the failure mode you cannot see from inside: a customer
    asking a real question gets routed to a queue and nothing logs it wrong."""
    assert _ask(client, message)["intent"] != "human_request", message


# ------------------------------------------- Ethiopic inflection, both ways


@pytest.mark.parametrize("message", [
    # Ethiopic inflects the FINAL character rather than appending to it, so
    # matching a noun's citation form misses every inflected use of it.
    # አመራር -> አመራሩ was classified as an ordinary question.
    "ከአመራሩ ጋር መነጋገር እፈልጋለሁ",
    "አመራሩን ማነጋገር እፈልጋለሁ",
    "ሥራ አስኪያጁን ማነጋገር እፈልጋለሁ",   # አስኪያጅ -> አስኪያጁ
    "ማኔጀሩን ማነጋገር እፈልጋለሁ",        # ማኔጀር  -> ማኔጀሩ
    # These three are stable under suffixing and were already fine — kept so a
    # future rewrite of the character classes cannot quietly drop them.
    "ኃላፊውን ማነጋገር እፈልጋለሁ",
    "ከአለቃው ጋር መነጋገር እፈልጋለሁ",
    "ተቆጣጣሪውን ማነጋገር እችላለሁ?",
])
def test_inflected_manager_words_still_escalate(
    client: TestClient, demo_bank: Any, message: str
) -> None:
    assert _ask(client, message)["intent"] == "human_request", message


@pytest.mark.parametrize("message", [
    # ኃላፊነት is "responsibility/role" and contains ኃላፊ outright. The first
    # guard was (?!ነት), which the inflected forms walk straight past: ኃላፊነቱ is
    # ኃላፊ + ነ + ቱ and contains no "ነት" at all. Hence (?!ነ).
    "የባንኩ ኃላፊነት ምንድን ነው?",
    "የባንኩ ኃላፊነቱ ምንድን ነው?",
    "የባንኩ ኃላፊነቷ ምንድን ነው?",
    "ኃላፊነታችን ምንድን ነው?",
    "የደንበኛው ኃላፊነትን ማወቅ እፈልጋለሁ",
])
def test_a_question_about_responsibility_is_not_a_demand_for_a_manager(
    client: TestClient, demo_bank: Any, message: str
) -> None:
    """Asking what the bank is responsible for is a question about the bank,
    not a request to escalate. Routing it to a queue answers something the
    customer did not ask and logs nothing as wrong."""
    assert _ask(client, message)["intent"] != "human_request", message


# ------------------------------------------------- the adjective in the way


@pytest.mark.parametrize(
    "message",
    [
        # Reported from the deployed demo. The article had to sit flush
        # against the noun, so a single adjective between them dropped the
        # request to an ordinary question — and "live agent" is the commonest
        # way an English speaker asks for one.
        "Can I speak to a live agent?",
        "I want to speak to a live agent",
        "speak to a live person",
        "Can I talk to a live representative?",
        "I need a live agent",
        "live agent please",
        "I want to chat with a real person",
        # A bank. The word for the thing this product is built around was
        # missing from the noun list entirely.
        "talk to a teller",
        "Can I speak to a teller?",
    ],
)
def test_an_adjective_between_the_article_and_the_noun_still_escalates(
    message: str,
) -> None:
    assert classifier.classify_intent(message) == classifier.HUMAN_REQUEST


@pytest.mark.parametrize(
    "message",
    [
        # AGENT BANKING IS A REAL ETHIOPIAN BANKING PRODUCT. This is why the
        # bare-phrase rule requires an adjective: matching "agent" on its own
        # would turn a customer asking about the agent network into a demand
        # for a manager, and silently stop answering a question the bank has
        # published content for.
        "Do you have agent banking?",
        "What is agent banking?",
        "How do I become a banking agent?",
        "Where is your nearest agent?",
        "Can I open an account with an agent?",
        # Same for teller, now that it is a noun in the list.
        "Is there a teller at every branch?",
        "What are teller working hours?",
    ],
)
def test_asking_about_agents_and_tellers_is_still_a_question(message: str) -> None:
    assert classifier.classify_intent(message) == classifier.QUESTION


def test_a_live_agent_request_gets_no_unrelated_suggestions(
    client: TestClient, demo_bank: Any
) -> None:
    """The screenshot that started this: "Can I speak to a live agent?" was
    answered with "I don't have verified information about that yet" and three
    suggested articles — Treasury Bills, Saving and Budgeting, Diaspora
    Accounts. Retrieval had been asked a question nobody posed.
    """
    body = _ask(client, "Can I speak to a live agent?")
    assert body["intent"] == classifier.HUMAN_REQUEST
    assert not body.get("suggestions")
    assert "verified information" not in body["reply"]


@pytest.mark.parametrize(
    "message",
    [
        # Reported from the demo exactly like this: a phone keyboard split
        # "agent" into "a gent" and the noun list could not match half a word.
        "Can I speak to a live a gent",
        "Can I speak to a live agnet",
        "speak to a live gent",
        "chat with a live operater",
        "talk to a real advisor",
    ],
)
def test_a_mistyped_noun_after_live_still_escalates(message: str) -> None:
    """Chasing individual typos is endless. What carries the meaning is
    "live" inside a speak-to construction, whatever noun follows — so the
    rule matches on that pair instead of on a spelling."""
    assert classifier.classify_intent(message) == classifier.HUMAN_REQUEST


def test_live_on_its_own_is_not_a_request_for_a_person() -> None:
    """Both halves are required. A bank publishes live rates and live feeds,
    and matching "live" alone would turn those questions into escalations."""
    for message in (
        "Do you have a live rate feed?",
        "Are your exchange rates live?",
        "Is the live chat available at night?",
    ):
        assert classifier.classify_intent(message) == classifier.QUESTION, message
