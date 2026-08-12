"""A conversation records when it happened, and says so.

Every message has carried a `created_at` since the first migration, and every
endpoint that returns messages has put it on the wire. Not one surface
rendered it. An admin reading a transcript could not tell whether two lines
were four seconds or four days apart; a teller picking up a live session saw
the customer's whole prior history — which is deliberate, the thread is not
trimmed to the call — with nothing to say which parts were from ten minutes
ago and which from last week. The conversation list showed a relative age
that degraded to "41 days", which is not an answer to "which day did this
happen" and is exactly the question a bank gets asked about a complaint.

The data was there the whole time. The display layer dropped it, everywhere.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist.api import iso
from bankassist.i18n import SUPPORTED_LANGUAGES

ADMIN = Path("bankassist/static/admin.html")
WIDGET = Path("bankassist/static/widget.html")


# ------------------------------------------------------------- the wire


def test_a_naive_timestamp_goes_out_with_an_offset() -> None:
    """The bug underneath all of this.

    SQLite has no timezone type, so a `DateTime(timezone=True)` column comes
    back naive and `.isoformat()` produced "2026-08-10T19:12:33" — which the
    ECMAScript spec says a browser must read as LOCAL time. In Addis that put
    every message three hours into the future, so a conversation that had just
    happened rendered as a NEGATIVE age. Postgres returns aware values, so
    production was never affected; that is luck, not design.
    """
    naive = datetime(2026, 8, 10, 19, 12, 33)
    assert naive.tzinfo is None
    out = iso(naive)
    assert out is not None
    assert out.endswith("+00:00"), f"no offset on the wire: {out}"
    # And the value is not shifted — a naive UTC value is UTC with its label
    # lost, so attaching the label back must not move the instant.
    assert datetime.fromisoformat(out) == naive.replace(tzinfo=UTC)


def test_an_aware_timestamp_is_left_alone() -> None:
    aware = datetime(2026, 8, 10, 19, 12, 33, tzinfo=UTC)
    assert iso(aware) == aware.isoformat()


def test_none_survives() -> None:
    """`resolved_at` and `last_login_at` are legitimately null."""
    assert iso(None) is None


def test_no_endpoint_formats_a_model_timestamp_by_hand() -> None:
    """One helper, or the next timestamp added goes back to being naive."""
    src = Path("bankassist/api.py").read_text(encoding="utf-8")
    body = src.split("def iso(", 1)[1].split("\n@app", 1)[1]
    stragglers = [
        line.strip()
        for line in body.splitlines()
        # `.date().isoformat()` is a date, which has no offset to lose.
        if ".isoformat()" in line and ".date()" not in line
    ]
    assert not stragglers, (
        f"these bypass iso() and will go out naive on SQLite: {stragglers}"
    )


def test_the_message_endpoint_still_carries_the_time(
    client: TestClient, demo_bank: Any
) -> None:
    """The field the display layer was dropping. If it ever stops being sent,
    every timestamp on every surface silently becomes blank."""
    client.post(
        f"/chat/{demo_bank.slug}",
        json={"message": "What documents do I need to open an account?"},
    )
    auth = {"X-Admin-Token": demo_bank.admin_token}
    convos = client.get(
        f"/admin/api/{demo_bank.slug}/conversations", headers=auth
    ).json()
    assert convos
    assert convos[0]["created_at"].endswith(("+00:00", "Z"))
    msgs = client.get(
        f"/admin/api/{demo_bank.slug}/conversations/{convos[0]['id']}/messages",
        headers=auth,
    ).json()
    assert msgs
    for m in msgs:
        assert m["created_at"], "a message with no time"
        assert m["created_at"].endswith(("+00:00", "Z"))


# ------------------------------------------------------------- the screen


@pytest.mark.parametrize(
    "marker",
    [
        # The three admin transcripts, all routed through one separator helper
        # so they cannot drift apart again.
        "function withDaySeparators",
        "function clockOf",
        "function dayLabel",
        "function stampOf",
    ],
)
def test_the_admin_has_the_clock_helpers(marker: str) -> None:
    assert marker in ADMIN.read_text(encoding="utf-8")


def test_every_admin_transcript_renders_a_time() -> None:
    """Three of them: the conversations page, the escalation card, and the
    teller's call room. All three dropped it; all three must show it."""
    html = ADMIN.read_text(encoding="utf-8")
    # One call site per transcript, plus the definition.
    assert html.count("withDaySeparators(") >= 4
    # Nothing may render a bare message row again.
    assert '\'<div class="msgline \' + esc(m.role) + \'">\'' not in html
    assert '\'<div class="msg2 \' + cls + \'">\'' not in html


def test_the_teller_is_told_where_the_call_began() -> None:
    """The thread deliberately carries the WHOLE conversation, not just the
    call — so without a mark, a teller cannot tell which lines they are
    joining from which the assistant handled last week."""
    html = ADMIN.read_text(encoding="utf-8")
    block = html.split("function drawThread")[1].split("function stopCallChat")[0]
    assert "callSession.requested_at" in block
    assert 'A("call_started")' in block


def test_the_conversation_list_gives_an_exact_time() -> None:
    """A relative age answers "is this urgent". Only an absolute one answers
    "which day did this happen", and past 48 hours the relative one was all
    there was."""
    html = ADMIN.read_text(encoding="utf-8")
    assert 'title="\' + esc(stampOf(c.created_at))' in html
    # And the bucket past two days is a date now, not "41 days".
    block = html.split("function waited(")[1].split("\n}")[0]
    assert "onDay(iso)" in block
    assert '" days"' not in block


def test_conversations_can_be_exported() -> None:
    """The one list a bank is asked to produce when someone disputes what was
    said. It was the only list with no export."""
    html = ADMIN.read_text(encoding="utf-8")
    assert "function exportConvos" in html
    block = html.split("function exportConvos")[1].split("\n}")[0]
    assert '"Started"' in block, "the timestamp is the point of this file"
    assert "csvCell" in block, "a name starting with = must not execute in Excel"
    assert 'id="dl-convos"' in html


def test_the_widget_stamps_both_of_its_chats() -> None:
    html = WIDGET.read_text(encoding="utf-8")
    assert "function stampOn" in html
    assert "function dayOf" in html
    # The bot chat, and the live teller chat.
    assert html.count("stampOn(turn") >= 3
    assert 'textEl("stamp2"' in html


def test_the_widget_builds_stamps_as_text_not_markup() -> None:
    """`el(tag, cls, html)` sets innerHTML from its THIRD argument. A
    four-argument call is silently ignored, which rendered empty stamps; and a
    translated day label has no business going through innerHTML at all."""
    html = WIDGET.read_text(encoding="utf-8")
    # The exact signature. A substring match passed a mutation that renamed
    # this to textElXX, because "function textEl" is a prefix of it.
    assert "function textEl(cls, text) {" in html
    block = html.split("function textEl(cls, text) {")[1].split("\n  }")[0]
    assert "textContent" in block
    assert "innerHTML" not in block
    # And it is what the stamps actually go through.
    assert 'textEl("stamp"' in html and 'textEl("stamp2"' in html and 'textEl("daysep2"' in html


# --------------------------------------------------------- five languages


def test_the_new_labels_ship_in_every_language() -> None:
    """Rule 2b. A date separator reading "Today" is the one English word left
    on an otherwise Amharic screen."""
    admin = json.loads(Path("bankassist/admin_strings.json").read_text(encoding="utf-8"))
    ui = json.loads(Path("bankassist/ui_strings.json").read_text(encoding="utf-8"))
    for table, keys in (
        (admin, ["today", "yesterday", "call_started", "no_messages"]),
        (ui, ["today", "yesterday"]),
    ):
        for key in keys:
            for lang in SUPPORTED_LANGUAGES:
                assert table[lang].get(key, "").strip(), f"{key} missing for {lang}"
            for lang in ("am", "om", "ti", "so", "sw"):
                assert table[lang][key] != table["en"][key], f"{key} still English in {lang}"


def test_the_clock_follows_the_chosen_language() -> None:
    """toLocaleTimeString with no locale uses the BROWSER's, so an Amharic
    panel on an English laptop would show its one remaining English word in
    the timestamp."""
    for path, lang_var in ((ADMIN, "adminLang"), (WIDGET, "uiLang")):
        html = path.read_text(encoding="utf-8")
        # Dates and times only. num() formats integers with
        # toLocaleString() and should keep following the browser.
        for call in re.findall(r"toLocale(?:Date|Time)String\(([^)]*)", html):
            assert lang_var in call, f"{path.name}: a bare toLocale…String({call[:30]})"
        for call in re.findall(r"new Date\([^)]*\)\.toLocaleString\(([^)]*)", html):
            assert lang_var in call, f"{path.name}: a bare Date.toLocaleString({call[:30]})"
