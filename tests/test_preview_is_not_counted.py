"""The Dashboard's Live Preview must never reach a report.

The preview runs the real widget against the real assistant — that is what
makes it worth having. But the person typing into it is the bank's own staff,
and every reporting surface in this product exists to describe *customers*.

Found by driving an empty tenant in a browser rather than by reading the code:
the preview's own suggestion chips ("How do I open an account?") each earned
the I-don't-know reply, filed a Handoff, asked the admin for a phone number,
and seeded Content Gaps with the questions the admin had just tapped. Every
report was individually correct about the rows it was handed. Nothing was
wrong except which rows those were.

`test_no_report_counts_preview_traffic` is the load-bearing one: it walks the
reporting endpoints as a table rather than asserting about them one at a time,
so the *next* report added either excludes preview traffic or fails here. That
is the same shape as `test_channel_connect_ui.py`, and for the same reason —
the failure mode is forgetting a site, not getting a site wrong.
"""

from __future__ import annotations

from typing import Any

from conftest import create_user
from fastapi.testclient import TestClient

from bankassist import channels
from bankassist.models import Conversation

# Every admin surface that reports on customers. A report absent from this
# tuple is not covered, so adding one here is part of adding a report.
REPORTS: tuple[str, ...] = (
    "analytics",
    "analytics/operations",
    "analytics/insights",
    "content-gaps",
    "handoffs?status=all",
)


PW = "Passw0rd!2345"


def _signed_in(client: TestClient, demo_bank: Any, slug: str = "demo") -> TestClient:
    """The tenant's first user is an admin, then signed in — see conftest."""
    create_user(client, demo_bank, "boss@demo.et", password=PW, role="admin", slug=slug)
    r = client.post(
        f"/admin/api/{slug}/login", json={"email": "boss@demo.et", "password": PW}
    )
    assert r.status_code == 200, r.text
    return client


def _preview_conversation(client: TestClient, slug: str = "demo") -> str:
    r = client.post(f"/admin/api/{slug}/preview/conversation")
    assert r.status_code == 201, r.text
    cid: str = r.json()["conversation_id"]
    return cid


def _ask(client: TestClient, cid: str, text: str, slug: str = "demo") -> dict[str, Any]:
    r = client.post(
        f"/chat/{slug}", json={"message": text, "conversation_id": cid}
    )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _blob(client: TestClient, path: str, slug: str = "demo") -> str:
    sep = "&" if "?" in path else "?"
    r = client.get(f"/admin/api/{slug}/{path}{sep}days=365")
    assert r.status_code == 200, (path, r.text)
    return r.text


def test_the_preview_route_stamps_the_channel(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    _signed_in(client, demo_bank)
    cid = _preview_conversation(client)
    convo = db_session.get(Conversation, cid)
    assert convo is not None
    assert convo.channel == channels.PREVIEW


def test_preview_is_not_a_connectable_channel(client: TestClient) -> None:
    """It is an origin, not a channel. The Channels page must not offer it.

    `test_channel_connect_ui.py` demands a connect form for every catalogue
    entry; a preview has nothing to connect and is not a way a customer
    reaches the bank.
    """
    assert channels.PREVIEW not in {entry["key"] for entry in channels.CATALOGUE}


def test_no_report_counts_preview_traffic(client: TestClient, demo_bank: Any) -> None:
    """The whole point. Ask through the preview; no report may mention it."""
    _signed_in(client, demo_bank)
    cid = _preview_conversation(client)
    # A question this tenant cannot answer, so it takes every path that
    # records something: unanswered outcome, handoff, contact request, gap.
    needle = "zqxwv preview probe about nothing at all"
    reply = _ask(client, cid, needle)
    assert reply["handoff_created"] is True, (
        "the probe must actually reach the recording paths, or this test "
        "passes by asking nothing"
    )

    for path in REPORTS:
        assert needle not in _blob(client, path), (
            f"/{path} contains text typed into the Live Preview. A staff "
            f"member trying the product is not a customer asking a question."
        )


def test_preview_does_not_move_the_deflection_rate(client: TestClient, demo_bank: Any) -> None:
    """The number a bank decides renewal on, specifically.

    Counting a staff member's unanswered test question drags deflection down;
    counting an answered one flatters it. Both are the same bug.
    """
    _signed_in(client, demo_bank)
    before = client.get("/admin/api/demo/analytics?days=365").json()

    cid = _preview_conversation(client)
    for _ in range(3):
        _ask(client, cid, "zqxwv preview probe about nothing at all")

    after = client.get("/admin/api/demo/analytics?days=365").json()
    assert after["conversations"] == before["conversations"]
    assert after["substantive_questions"] == before["substantive_questions"]
    assert after["deflection_rate"] == before["deflection_rate"]


def test_preview_still_appears_in_conversations(client: TestClient, demo_bank: Any) -> None:
    """Excluded from reports, NOT hidden.

    The card's caption promises these messages appear in Conversations, and a
    staff member who tests a wording is entitled to read the transcript back.
    Suppressing the row entirely would be a different lie.
    """
    _signed_in(client, demo_bank)
    cid = _preview_conversation(client)
    _ask(client, cid, "zqxwv preview probe about nothing at all")

    rows = client.get("/admin/api/demo/conversations").json()
    assert any(row["id"] == cid for row in rows), (
        "the preview conversation vanished from Conversations, which the "
        "preview card explicitly promises it will not"
    )


def test_a_customer_cannot_mark_their_own_traffic_uncounted(client: TestClient) -> None:
    """The reason this is a route and not `?preview=1` on /chat.

    Deciding what a bank's reports do not show is a privilege. If the widget
    could assert it, so could anyone with the embed URL — and a bank's Content
    Gaps would be missing whatever a caller preferred it not to see.
    """
    r = client.post("/admin/api/demo/preview/conversation")
    assert r.status_code in (401, 403), r.text


def test_ordinary_traffic_is_still_counted(client: TestClient, demo_bank: Any) -> None:
    """The negative direction, which is the one a filter breaks.

    An exclusion that quietly swallowed real customers would look exactly like
    a working fix from inside every test above.
    """
    _signed_in(client, demo_bank)
    needle = "zqxwv ordinary customer probe about nothing at all"
    r = client.post("/chat/demo", json={"message": needle})
    assert r.status_code == 200, r.text
    assert r.json()["handoff_created"] is True

    assert needle in _blob(client, "content-gaps")
    assert client.get("/admin/api/demo/analytics?days=365").json()["conversations"] >= 1
