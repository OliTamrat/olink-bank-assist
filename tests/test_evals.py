"""The golden-question suite must pass in extractive mode on every commit."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from bankassist.evals import load_cases, run


def test_golden_suite(client: TestClient, demo_bank: Any) -> None:
    def ask(question: str) -> dict[str, Any]:
        resp = client.post("/chat/demo", json={"message": question})
        assert resp.status_code == 200, resp.text
        data: dict[str, Any] = resp.json()
        return data

    results = run(ask)
    failed = [r for r in results if not r.passed]
    assert not failed, "\n".join(f"{r.case_id}: {'; '.join(r.failures)}" for r in failed)


def test_golden_file_is_well_formed() -> None:
    cases = load_cases()
    assert len(cases) >= 10
    assert len({c.id for c in cases}) == len(cases), "duplicate case ids"
    for case in cases:
        checks_something = (
            case.expect_intent is not None
            or case.expect_language is not None
            or case.expect_handoff is not None
            or case.must_contain_any
            or case.must_not_contain
        )
        assert checks_something, f"case {case.id} asserts nothing"
