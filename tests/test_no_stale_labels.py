"""A label table must never be more cacheable than the page that reads it.

Reported from the deployed panel: "the translation is only applied on the
sidebar and navbar but the dashboard is still only in English."

The code was right — switching the picker re-renders every page, verified in
a browser. What was wrong was what reached the browser. `/admin` is served
`no-store`, so the PAGE is always fresh, but `/admin/strings` carried no
cache headers at all, and a response with no explicit freshness information
may be held under the browser's own heuristic (RFC 9111 §4.2.2).

A fresh page against a stale table is a specific failure, not a general one.
Every key that existed when the table was cached still renders translated;
every key added since does not. The sidebar was translated in one release and
the dashboard in the next — so the sidebar's keys are in the cached copy and
the dashboard's are not, and it looks precisely like a half-finished
translation.

`/banks/{slug}/public` is in here for the same reason plus a worse one: it
carries `teller_available`, a live operational switch. A bank turning live
sessions on and staying invisible to customers behind a cached `false` is not
a cosmetic problem.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

# Every response that feeds a no-store page. The page and its data have to
# age together or they disagree, and the disagreement is invisible.
MUST_NOT_BE_CACHED = [
    ("/admin", "the admin page itself"),
    ("/widget", "the widget page itself"),
    ("/admin/strings", "the admin's label table"),
    ("/banks/demo/public", "the widget's labels, brand and teller switch"),
]


@pytest.mark.parametrize(
    "path,what", MUST_NOT_BE_CACHED, ids=[c[0] for c in MUST_NOT_BE_CACHED]
)
def test_it_is_not_cacheable(
    client: TestClient, demo_bank: Any, path: str, what: str
) -> None:
    resp = client.get(path)
    assert resp.status_code == 200
    cache = resp.headers.get("cache-control", "")
    assert "no-store" in cache, (
        f"{path} ({what}) may be cached: cache-control={cache!r}. "
        "A stale copy of this desynchronises from the page that reads it."
    )


def test_the_admin_labels_are_actually_served(client: TestClient) -> None:
    """The endpoint has to keep working, not merely keep its headers."""
    body = client.get("/admin/strings").json()
    assert set(body) >= {"en", "am", "om", "ti", "so", "sw"}
    # A key from the batch that exposed this — the dashboard's, not the nav's.
    assert body["am"]["questions_asked"] != body["en"]["questions_asked"]


def test_the_public_payload_still_carries_what_the_widget_needs(
    client: TestClient, demo_bank: Any
) -> None:
    body = client.get("/banks/demo/public").json()
    assert "ui" in body
    assert "teller_available" in body
