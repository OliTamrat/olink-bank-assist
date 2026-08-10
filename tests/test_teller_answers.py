"""The bank's approved wording, searchable while a teller is on a call.

No teller carries a hundred and sixty answers in their head. Without this the
bank's own approved text sits one table away from somebody improvising a fee
from memory — and it is the same text the bot serves, so the human and the
machine giving different answers to the same question is a bank getting the
worst of both at once.

The property that matters is not the search. It is that a teller is handed
ONLY wording the bank stands behind: a draft is somebody's half-written
afternoon, and reading it aloud to a customer is exactly the harm draft status
exists to prevent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ADMIN = Path("bankassist/static/admin.html")


def _write(client: TestClient, bank: Any, question: str, answer: str,
           status: str) -> None:
    client.post(
        "/admin/api/demo/faq",
        json={"question": question, "answer": answer, "status": status},
        headers={"X-Admin-Token": bank.admin_token},
    )


def test_a_teller_is_never_handed_a_draft(
    client: TestClient, demo_bank: Any
) -> None:
    """The one that matters. Filtered on the server so the drafts are never
    sent to the browser at all — a client-side filter is a courtesy, and this
    is a control."""
    _write(client, demo_bank, "What is the transfer fee?", "Ten birr.", "published")
    _write(client, demo_bank, "What is the loan rate?", "half-written…", "draft")
    rows = client.get(
        "/admin/api/demo/faq?status=published",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    questions = {r["question"] for r in rows}
    assert "What is the transfer fee?" in questions
    assert "What is the loan rate?" not in questions
    assert all(r["status"] == "published" for r in rows)


def test_the_unfiltered_list_still_shows_everything(
    client: TestClient, demo_bank: Any
) -> None:
    """The admin writing answers needs to see their own drafts. Only the
    teller's view is narrowed."""
    _write(client, demo_bank, "What is the transfer fee?", "Ten birr.", "published")
    _write(client, demo_bank, "What is the loan rate?", "half-written…", "draft")
    rows = client.get(
        "/admin/api/demo/faq", headers={"X-Admin-Token": demo_bank.admin_token}
    ).json()
    assert {r["status"] for r in rows} == {"published", "draft"}


def test_an_unknown_status_is_refused(client: TestClient, demo_bank: Any) -> None:
    """Refused rather than ignored. A typo silently returning everything is
    how a draft reaches a teller's screen without anybody noticing."""
    assert client.get(
        "/admin/api/demo/faq?status=approved",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).status_code == 422


def test_the_filter_is_still_tenant_scoped(
    client: TestClient, demo_bank: Any, second_bank: Any
) -> None:
    _write(client, demo_bank, "What is the transfer fee?", "Ten birr.", "published")
    rows = client.get(
        "/admin/api/other/faq?status=published",
        headers={"X-Admin-Token": second_bank.admin_token},
    ).json()
    assert rows == []


def test_the_console_asks_for_published_only() -> None:
    """Pins the request the teller console actually makes. The server control
    is worth nothing if the console quietly asks for everything."""
    html = ADMIN.read_text(encoding="utf-8")
    assert "/faq?status=published" in html
    assert "loadApprovedAnswers" in html


def test_choosing_an_answer_fills_the_composer_rather_than_sending() -> None:
    """A teller reads it, adapts it to what was actually asked, and takes
    responsibility for what goes out. Auto-sending would make this a bot with
    a person watching — the opposite of what somebody asked for when they
    asked for a human."""
    html = ADMIN.read_text(encoding="utf-8")
    marker = html.split("function renderAnswers")[1].split("function startCallChat")[0]
    assert "say.value = row.answer" in marker
    assert "say.focus()" in marker
    # No send call anywhere in the click handler.
    assert "sendCallMessage" not in marker
    assert "callComposer" not in marker


def test_the_search_is_wired_once_not_per_call() -> None:
    """Re-binding on every open stacks handlers, so the list re-renders once
    per call ever taken — invisible on the first call and unusable by the
    twentieth."""
    html = ADMIN.read_text(encoding="utf-8")
    assert "wireAnswerSearch" in html
    assert html.count('getElementById("ansQ")') == 1
