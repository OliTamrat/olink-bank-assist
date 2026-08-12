"""AI insights — the model is the analyst; the rules are the offline floor.

The properties held here: every fallback rule fires on its threshold and
stays quiet under its denominator floor (a rate over three events is noise);
the page is never empty; the endpoint works with no model at all; the brief
digest physically excludes the one aggregate field carrying customer
wording; and a failed or malformed model reply degrades to the findings
rather than an error or a half-parsed page.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import insights, llm


def _overview(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "window_days": 30,
        "since": None,
        "conversations": 40,
        "substantive_questions": 0,
        "deflection_rate": None,
        "own_content_rate": None,
        "previous": None,
        "languages": [],
        "top_topics": [{"example": "SHOULD NEVER BE READ"}],
    }
    base.update(over)
    return base


def _ops(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "escalations": {
            "open": 0, "urgent_open": 0, "filed": 0, "resolved": 0,
            "avg_resolution_seconds": None, "desks": [],
        },
        "live": {
            "requested": 0, "claimed": 0, "abandoned": 0,
            "avg_wait_seconds": None, "avg_handle_seconds": None,
        },
        "staffing": {"front_line": 0, "on_duty_now": 0},
        "busy": [],
    }
    base.update(over)
    return base


def _keys(found: list[dict[str, Any]]) -> list[str]:
    return [f["key"] for f in found]


# ------------------------------------------------------------------- rules


def test_a_quiet_window_still_says_something() -> None:
    found = insights.findings(_overview(), _ops())
    assert _keys(found) == ["all_quiet"]


def test_urgent_open_work_is_an_act_finding() -> None:
    ops = _ops()
    ops["escalations"]["urgent_open"] = 2
    found = insights.findings(_overview(), ops)
    assert found[0]["key"] == "urgent_open"
    assert found[0]["severity"] == "act"
    assert found[0]["vars"] == {"n": 2}


def test_abandonment_needs_a_real_denominator() -> None:
    ops = _ops()
    ops["live"].update({"requested": 3, "abandoned": 3})
    assert "abandonment" not in _keys(insights.findings(_overview(), ops))
    ops["live"].update({"requested": 8, "abandoned": 3})
    found = insights.findings(_overview(), ops)
    assert "abandonment" in _keys(found)


def test_low_own_content_fires_only_with_enough_questions() -> None:
    over = _overview(substantive_questions=5, own_content_rate=0.2)
    assert "own_content_low" not in _keys(insights.findings(over, _ops()))
    over = _overview(substantive_questions=20, own_content_rate=0.2)
    assert "own_content_low" in _keys(insights.findings(over, _ops()))


def test_the_slowest_desk_is_named_once_not_listed() -> None:
    ops = _ops()
    ops["escalations"].update({
        "avg_resolution_seconds": 10 * 3600, "resolved": 10,
        "desks": [
            {"department": "cards", "label": "Cards & ATM",
             "resolved": 4, "avg_resolution_seconds": 40 * 3600},
            {"department": "lending", "label": "Loans & credit",
             "resolved": 4, "avg_resolution_seconds": 50 * 3600},
        ],
    })
    found = insights.findings(_overview(), ops)
    slow = [f for f in found if f["key"] == "slow_desk"]
    assert len(slow) == 1
    assert slow[0]["vars"]["desk"] == "Cards & ATM"


def test_deflection_shift_compares_against_the_previous_window() -> None:
    over = _overview(
        substantive_questions=30, deflection_rate=0.50,
        previous={"deflection_rate": 0.62},
    )
    found = insights.findings(over, _ops())
    assert "deflection_down" in _keys(found)
    over["deflection_rate"] = 0.70
    found = insights.findings(over, _ops())
    assert "deflection_up" in _keys(found)
    assert "deflection_good" in _keys(found)


def test_a_language_missing_answers_is_flagged() -> None:
    over = _overview(languages=[
        {"language": "so", "name": "Soomaali",
         "outcomes": {"answered": 4, "unanswered": 6}},
    ])
    found = insights.findings(over, _ops())
    flag = next(f for f in found if f["key"] == "lang_gap")
    assert flag["vars"]["language"] == "Soomaali"
    assert flag["vars"]["pct"] == 60


def test_the_peak_hour_is_reported_in_utc_for_the_client_to_shift() -> None:
    ops = _ops(busy=[[0, 8, 10], [1, 8, 10], [2, 14, 1], [3, 15, 1]])
    found = insights.findings(_overview(), ops)
    peak = next(f for f in found if f["key"] == "peak_hour")
    assert peak["vars"] == {"utc_hour": 8}


def test_act_findings_always_sort_first() -> None:
    over = _overview(substantive_questions=30, deflection_rate=0.9)
    ops = _ops()
    ops["escalations"]["urgent_open"] = 1
    found = insights.findings(over, ops)
    assert found[0]["severity"] == "act"
    assert found[-1]["severity"] == "good"


def test_every_finding_key_has_a_translated_template() -> None:
    """A finding the panel cannot render is a finding nobody reads. Every
    key this module can emit must exist as insight_<key> in all six
    languages of the admin table."""
    import json as json_module
    from pathlib import Path

    table = json_module.loads(
        (Path(__file__).resolve().parent.parent / "bankassist"
         / "admin_strings.json").read_text(encoding="utf-8")
    )
    emittable = {
        "urgent_open", "abandonment", "own_content_low", "slow_resolution",
        "slow_desk", "nobody_on", "deflection_up", "deflection_down",
        "lang_gap", "peak_hour", "deflection_good", "all_quiet",
    }
    for lang, strings in table.items():
        for key in emittable:
            assert f"insight_{key}" in strings, (lang, key)


# ---------------------------------------------------------- the endpoint


def _get(client: TestClient, bank: Any, **params: Any) -> dict[str, Any]:
    resp = client.get(
        f"/admin/api/{bank.slug}/analytics/insights",
        headers={"X-Admin-Token": bank.admin_token},
        params=params,
    )
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def test_the_endpoint_works_with_no_model_at_all(
    client: TestClient, demo_bank: Any
) -> None:
    data = _get(client, demo_bank)
    assert data["findings"]
    assert data["brief"] is None
    assert data["backend"] == "extractive-fallback"


BRIEF_JSON = (
    '{"headline": "A quiet week.", '
    '"assessment": [{"title": "Volume", "body": "Steady."}], '
    '"actions": [{"text": "Keep going.", "priority": "later"}]}'
)


def test_the_brief_digest_never_carries_customer_text(
    client: TestClient, demo_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The customer's own words reach Overview only inside top_topics
    (already redacted). The digest must not include that field at all —
    the model cannot quote what it was never given."""
    r = client.post(
        "/chat/demo",
        json={"message": "What is the atmosphere on the moon made of?"},
    )
    assert r.status_code == 200

    captured: dict[str, str] = {}

    def fake_call(system: str, user: str, max_output_tokens: int,
                  *, thinking_budget: int) -> str:
        captured["system"] = system
        captured["user"] = user
        return BRIEF_JSON

    monkeypatch.setattr(llm, "_call_model", fake_call)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    data = _get(client, demo_bank, brief=1, language="am")
    assert data["brief"]["headline"] == "A quiet week."
    assert data["brief"]["actions"][0]["priority"] == "later"
    assert data["brief_language"] == "am"
    assert "moon" not in captured["user"]
    assert "top_topics" not in captured["user"]
    # The model sees the full aggregate picture (it is the analyst now) and
    # the machine findings only as hints.
    assert "machine_findings" in captured["user"]
    # The brief is asked for in the panel's language, by its own name —
    # the same native names the rest of the product uses.
    assert "አማርኛ" in captured["system"]


def test_a_malformed_brief_degrades_rather_than_renders(
    client: TestClient, demo_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad_json(system: str, user: str, max_output_tokens: int,
                 *, thinking_budget: int) -> str:
        return "Here are my thoughts: the week was fine."

    monkeypatch.setattr(llm, "_call_model", bad_json)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    data = _get(client, demo_bank, brief=1)
    assert data["brief"] is None
    assert data["findings"]


def test_an_unknown_priority_is_coerced_never_crashed() -> None:
    parsed = llm._parse_brief(
        '{"headline": "x", "assessment": [{"title": "t", "body": "b"}], '
        '"actions": [{"text": "do", "priority": "immediately"}]}'
    )
    assert parsed["actions"][0]["priority"] == "soon"


def test_a_code_fenced_brief_still_parses() -> None:
    parsed = llm._parse_brief("```json\n" + BRIEF_JSON + "\n```")
    assert parsed["headline"] == "A quiet week."


def test_a_failed_model_call_degrades_to_findings(
    client: TestClient, demo_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(system: str, user: str, max_output_tokens: int,
               *, thinking_budget: int) -> str:
        raise llm.LLMUnavailable("down")

    monkeypatch.setattr(llm, "_call_model", broken)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    data = _get(client, demo_bank, brief=1)
    assert data["brief"] is None
    assert data["findings"]


def test_an_unknown_language_falls_back_to_english(
    client: TestClient, demo_bank: Any
) -> None:
    data = _get(client, demo_bank, language="fr")
    assert data["brief_language"] is None  # no brief requested
    assert data["findings"]


def test_one_banks_numbers_never_reach_anothers_insights(
    client: TestClient, demo_bank: Any, cbe_bank: Any
) -> None:
    r = client.post("/chat/demo", json={"message": "How do I open an account?"})
    assert r.status_code == 200
    ours = _get(client, demo_bank)
    theirs = _get(client, cbe_bank)
    # Isolation shows through the windowed counts the findings are built on.
    assert ours["since"] is not None and theirs["since"] is not None
    assert theirs["findings"][0]["key"] == "all_quiet"
