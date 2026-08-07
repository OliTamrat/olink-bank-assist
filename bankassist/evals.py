"""Golden-question eval suite — the pre-deploy gate.

Every case runs through the full agent pipeline against the seeded demo bank
and checks intent, language, required content, forbidden content, and handoff
behavior. CI runs it in extractive mode on every push (deterministic). Before
any model/prompt/KB change ships, run it manually in the target configuration:

    GEMINI_API_KEY=... python -m bankassist.evals

In LLM mode a wording-based failure needs human review before it's treated as
a regression — but guardrail cases (disclaimers, refusals, handoffs) are
enforced by code, not the model, and must never fail in either mode.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_GOLDEN_PATH = Path(__file__).resolve().parent / "golden_questions.json"

AskFn = Callable[[str], Mapping[str, Any]]
"""Takes a question, returns {reply, intent, language, handoff_created}."""


# Any money amount or percentage. An answer carrying no source cannot have got
# a figure from anywhere except the model's imagination, and a hallucinated
# rate or limit in a screenshot is what loses a bank deal — so this is
# enforced as an invariant rather than left to the prompt.
_FIGURE = re.compile(r"\d[\d,\.]*\s*(birr|etb|percent|%)|\bper cent\b", re.IGNORECASE)


@dataclass(frozen=True)
class GoldenCase:
    id: str
    question: str
    expect_intent: str | None = None
    expect_language: str | None = None
    expect_handoff: bool | None = None
    must_contain_any: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    # Regexes the reply must not match. Used for boundary cases where the
    # dangerous output cannot be enumerated as fixed strings.
    must_not_match: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    failures: list[str]

    @property
    def passed(self) -> bool:
        return not self.failures


def load_cases(path: Path = _GOLDEN_PATH) -> list[GoldenCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [GoldenCase(**entry) for entry in raw]


def check(case: GoldenCase, answer: Mapping[str, Any]) -> CaseResult:
    failures: list[str] = []
    reply = str(answer.get("reply", ""))
    if case.expect_intent is not None and answer.get("intent") != case.expect_intent:
        failures.append(f"intent={answer.get('intent')!r}, expected {case.expect_intent!r}")
    if case.expect_language is not None and answer.get("language") != case.expect_language:
        failures.append(f"language={answer.get('language')!r}, expected {case.expect_language!r}")
    if case.expect_handoff is not None:
        actual_handoff = bool(answer.get("handoff_created"))
        if actual_handoff != case.expect_handoff:
            failures.append(f"handoff={actual_handoff}, expected {case.expect_handoff}")
    if case.must_contain_any and not any(s in reply for s in case.must_contain_any):
        failures.append(f"reply contains none of {case.must_contain_any}")
    for forbidden in case.must_not_contain:
        if forbidden.lower() in reply.lower():
            failures.append(f"reply contains forbidden {forbidden!r}")
    for pattern in case.must_not_match:
        if re.search(pattern, reply, re.IGNORECASE):
            failures.append(f"reply matches forbidden pattern {pattern!r}")

    # Invariant, applied to every case rather than declared per case: a reply
    # with no sources came from no document, so any figure in it was invented.
    # This is the boundary that makes general-knowledge answers safe to ship,
    # and it holds in extractive mode and model mode alike.
    if not answer.get("sources") and answer.get("general_knowledge"):
        found = _FIGURE.search(reply)
        if found:
            failures.append(
                f"unsourced reply states a figure ({found.group(0)!r}) — "
                "the model invented a rate, fee or limit"
            )
    return CaseResult(case_id=case.id, failures=failures)


def run(ask: AskFn, cases: list[GoldenCase] | None = None) -> list[CaseResult]:
    return [check(case, ask(case.question)) for case in cases or load_cases()]


def main() -> int:
    import os

    tmp = tempfile.mkdtemp(prefix="bankassist-evals-")
    os.environ["BANKASSIST_DATABASE_URL"] = f"sqlite:///{tmp}/evals.db"

    from sqlalchemy.orm import sessionmaker

    from .agent import handle_message
    from .config import get_settings, reset_settings
    from .db import get_engine, reset_engine
    from .models import Bank, Conversation
    from .seed import seed

    reset_settings()
    reset_engine()
    seed()
    mode = "gemini" if get_settings().gemini_api_key else "extractive"

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)

    def ask(question: str) -> Mapping[str, Any]:
        with factory() as db:
            bank = db.query(Bank).filter_by(slug="demo").one()
            conversation = Conversation(bank_id=bank.id, channel="eval")
            db.add(conversation)
            db.flush()
            result = handle_message(db, bank, conversation, question)
            return {
                "reply": result.reply,
                "intent": result.intent,
                "language": result.language,
                "handoff_created": result.handoff_created,
                "sources": result.sources,
                "general_knowledge": result.general_knowledge,
            }

    results = run(ask)
    failed = [r for r in results if not r.passed]
    for r in results:
        marker = "PASS" if r.passed else "FAIL"
        print(f"[{marker}] {r.case_id}" + ("" if r.passed else f" — {'; '.join(r.failures)}"))
    print(f"\n{len(results) - len(failed)}/{len(results)} passed (mode: {mode})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
