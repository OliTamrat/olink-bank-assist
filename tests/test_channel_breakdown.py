"""The channel breakdown, and the colours the dashboard draws it in.

Two failures this file exists to catch, both of which shipped once.

**A breakdown built only from traffic cannot say what is missing.** Grouping
conversations by channel returns the channels that have conversations, so a
tenant using only the web widget got a chart reading "web, 100%". That is a
true sentence and a useless one: the fact a bank is deciding on is whether
WhatsApp is available, and a chart drawn from rows that exist renders "no
WhatsApp traffic" and "no WhatsApp" identically. The catalogue is therefore
the spine of the response and the counts are folded into it.

**Series colour must follow the entity, not its rank.** The dashboard keys its
palette off the language code and the channel key, so Amharic does not change
colour on the day it overtakes English. Those maps live in admin.html, which
has no test runner of its own, and a missing key fails silently — the series
renders grey and simply looks like a category nobody has used.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from bankassist import agent, channels
from bankassist.i18n import SUPPORTED_LANGUAGES

ADMIN = Path(agent.__file__).parent / "static" / "admin.html"


def _slots(name: str) -> dict[str, int]:
    block = re.search(rf"var {name} = \{{(.*?)\}};", ADMIN.read_text(), re.S)
    assert block, f"{name} not found in admin.html — did the palette map move?"
    return {
        key: int(slot)
        for key, slot in re.findall(r"(\w+):\s*(\d+)", block.group(1))
    }


def _analytics(client: TestClient, bank: Any) -> dict[str, Any]:
    resp = client.get(
        f"/admin/api/{bank.slug}/analytics",
        headers={"X-Admin-Token": bank.admin_token},
    )
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


# --------------------------------------------------------------- the response


def test_every_channel_is_listed_even_with_no_traffic(
    client: TestClient, demo_bank: Any
) -> None:
    """The point of the panel: absent and unavailable are different facts."""
    rows = _analytics(client, demo_bank)["channels"]
    listed = {row["channel"] for row in rows}
    for entry in channels.CATALOGUE:
        assert entry["key"] in listed, (
            f"{entry['key']} vanished from the breakdown. A bank reads that as "
            "the channel not existing, not as nobody having used it."
        )


def test_an_unused_channel_reports_zero_rather_than_being_dropped(
    client: TestClient, demo_bank: Any
) -> None:
    rows = {row["channel"]: row for row in _analytics(client, demo_bank)["channels"]}
    assert rows["whatsapp"]["count"] == 0
    # Built, but this tenant has pasted no credentials — "available", not
    # "live". Zero traffic on a connected channel and zero on an unconnected
    # one look identical in a count; the status is what separates them.
    assert rows["whatsapp"]["status"] == channels.AVAILABLE
    # The name is what a person reads; the key is what the code joins on.
    assert rows["whatsapp"]["name"] == "WhatsApp"


def test_traffic_is_counted_against_the_channel_it_arrived_on(
    client: TestClient, demo_bank: Any
) -> None:
    resp = client.post("/chat/demo", json={"message": "Selam!"})
    assert resp.status_code == 200, resp.text
    rows = {row["channel"]: row for row in _analytics(client, demo_bank)["channels"]}
    assert rows["web"]["count"] == 1
    assert rows["telegram"]["count"] == 0


def test_the_busiest_channel_sorts_first(client: TestClient, demo_bank: Any) -> None:
    """Ordering is part of the answer — the panel reads top-down."""
    client.post("/chat/demo", json={"message": "Selam!"})
    rows = _analytics(client, demo_bank)["channels"]
    counts = [int(row["count"]) for row in rows]
    assert counts == sorted(counts, reverse=True)


def test_the_outcome_tallies_survive_the_channel_query(
    client: TestClient, demo_bank: Any
) -> None:
    """A regression with an unglamorous cause: a shadowed local.

    The channel breakdown built a dict named `counts` in a function that
    already had one holding the outcome tallies, and the second assignment
    silently emptied "What happened to each question" while every channel
    number stayed correct. Nothing about the channel panel looked wrong, which
    is exactly why this assertion lives beside it rather than only in the
    analytics tests.
    """
    client.post("/chat/demo", json={"message": "Selam!"})
    data = _analytics(client, demo_bank)
    assert data["channels"], "channels should be populated"
    assert data["outcomes"], "outcomes was emptied by building the channel rows"


# ----------------------------------------------------------------- the colours


def test_every_channel_has_its_own_colour_slot() -> None:
    slots = _slots("CHANNEL_SLOT")
    for entry in channels.CATALOGUE:
        assert entry["key"] in slots, (
            f"{entry['key']} has no colour slot, so it draws grey and reads as "
            "an unrecognised category."
        )


def test_every_supported_language_has_its_own_colour_slot() -> None:
    slots = _slots("LANG_SLOT")
    for code in SUPPORTED_LANGUAGES:
        assert code in slots, f"{code} has no colour slot in the dashboard palette"


def test_no_two_series_share_a_slot() -> None:
    """Within one chart, two categories in the same colour is unreadable."""
    for name in ("CHANNEL_SLOT", "LANG_SLOT"):
        slots = _slots(name)
        assert len(set(slots.values())) == len(slots), f"{name} has a duplicate slot"


def test_slots_stay_inside_the_validated_palette() -> None:
    """Eight slots exist. A ninth would be a colour nobody validated.

    The palette's ordering is what makes it colour-blind-safe, and it was
    checked as a set of eight against this page's own surfaces. Slot 9 would
    be an invented hue, which is the one thing the method forbids outright.
    """
    defined = set(
        int(n) for n in re.findall(r"--series-(\d+):", ADMIN.read_text())
    )
    assert defined == set(range(1, 9)), f"expected slots 1-8, found {sorted(defined)}"
    for name in ("CHANNEL_SLOT", "LANG_SLOT"):
        for key, slot in _slots(name).items():
            assert slot in defined, f"{name}.{key} points at undefined --series-{slot}"


# ------------------------------------------------------- one home per control


def test_channels_is_a_destination_not_a_settings_tab() -> None:
    """Where customers reach you is not a preference.

    It was a read-only table inside Settings, which meant the page describing
    a channel was never the page that connected it — the Telegram token field
    sat three panels further down, under an unrelated heading.
    """
    src = ADMIN.read_text()
    assert re.search(r'id:\s*"channels".*load:\s*loadChannels', src), (
        "the Channels page is gone from the nav"
    )


def test_each_channel_control_has_exactly_one_home() -> None:
    """Duplication here is silent and expensive.

    Two Telegram token fields on two pages both look right; the second one to
    render wins the id, and the handler wires itself to whichever the DOM
    returns. Moving these out of Settings has to be a move, not a copy.
    """
    src = ADMIN.read_text()
    for element in ('id="tg-token"', 'id="embed-snip"', 'id="tg-save"'):
        assert src.count(element) == 1, f"{element} appears {src.count(element)} times"


def test_the_topbar_controls_the_boot_block_wires_still_exist() -> None:
    """A missing id here takes down the whole panel, not just one button.

    Boot does `$("refresh").innerHTML = …` with no null guard, so renaming or
    removing the element throws before any page loads and the admin renders as
    a blank screen with an error only in the console.
    """
    src = ADMIN.read_text()
    for element in ('id="refresh"', 'id="queue-btn"', 'id="queue-count"',
                    'id="stamp"', 'id="theme-toggle"'):
        assert element in src, f"{element} is wired at boot but no longer in the markup"
