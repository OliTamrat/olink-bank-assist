"""Every channel in the catalogue has a control that switches it on.

This exists because of a report, not a theory. The Channels page shipped with
a connect form for exactly two of its seven entries — the website embed and
Telegram. The other five described the channel, listed what it needs, and then
offered nothing to do about it. The backend had been finished the whole time:
`/viber/connect`, `/meta/connect` and `/sms/connect` were written, tested and
deployed. Only the five forms were missing, so the product looked half-built
from the one screen a bank actually uses to set it up.

Nothing caught it, and no test *could* have, because every existing check
asked a different question. `test_channel_breakdown` asks whether the
catalogue and the analytics agree. `test_docs_truth` asks whether the README's
channel count matches. `test_static_pages` asks whether the page's JavaScript
resolves. All were green while five channels had no way to be connected.

So the check here is the one that was missing: walk the catalogue — the same
tuple the page renders from — and require that `channelDetail` produces a
control for each key. It fails on the day an eighth channel is added to
`channels.py` without a form, which is precisely how the fifth one happened.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bankassist import channels

ADMIN = Path(__file__).resolve().parents[1] / "bankassist" / "static" / "admin.html"


@pytest.fixture(scope="module")
def page() -> str:
    return ADMIN.read_text(encoding="utf-8")


def _channel_detail(page: str) -> str:
    """The body of `channelDetail`, where the per-channel branch lives.

    Sliced rather than searched whole-file: the channel keys are ordinary
    words that appear all over this page — 'web' in a URL, 'sms' in a route —
    so a match anywhere else would let a channel with no form pass.
    """
    start = page.index("function channelDetail(")
    end = page.index("\nfunction wireChannelForms(", start)
    return page[start:end]


@pytest.mark.parametrize("key", [e["key"] for e in channels.CATALOGUE])
def test_every_channel_has_a_way_to_connect_it(page: str, key: str) -> None:
    body = _channel_detail(page)
    assert f'"{key}"' in body, (
        f"the Channels page describes {key!r} but has no branch that renders a "
        f"control for it. A channel the page explains and cannot connect reads "
        f"as an unfinished product — which is how this was reported."
    )


@pytest.mark.parametrize(
    ("key", "path"),
    [
        ("telegram", "/telegram/connect"),
        ("viber", "/viber/connect"),
        ("whatsapp", "/meta/connect"),
        ("messenger", "/meta/connect"),
        ("instagram", "/meta/connect"),
        ("sms", "/sms/connect"),
    ],
)
def test_each_form_posts_to_the_endpoint_that_exists(
    page: str, key: str, path: str
) -> None:
    """The form and the route it needs are written in different files, and the
    page is not type-checked. A typo'd path is a button that fails at the one
    moment a bank is trying to go live."""
    assert f'"{path}"' in page, f"{key} has no client call to {path}"


def test_the_meta_three_share_one_panel(page: str) -> None:
    """WhatsApp, Messenger and Instagram run through a single Meta app, so
    three separate panels would ask for the same app secret three times and
    let the second one overwrite the first with a typo."""
    body = _channel_detail(page)
    # Call sites, not the definition, which also lives inside this slice.
    assert body.count("h += metaPanel(") == 1, (
        "the Meta channels should route through one shared panel; separate "
        "panels drift and re-ask for the same app secret"
    )
    for key in ("whatsapp", "messenger", "instagram"):
        assert f'c.key === "{key}"' in body, f"{key} no longer reaches metaPanel"


def test_no_secret_is_rendered_into_a_readable_field(page: str) -> None:
    """Credential inputs are write-only.

    `/integrations` deliberately never returns a stored token, so a `value="`
    on one of these could only be populated from something that does — and a
    value the API will re-display is a value that ends up in a screenshot.
    """
    body = _channel_detail(page)
    for field in ("meta-secret", "meta-wa-token", "meta-ms-token",
                  "meta-ig-token", "sms-auth", "tg-token", "vb-token"):
        match = re.search(rf'id="{field}"[^>]*>', body)
        assert match, f"{field} is not rendered by channelDetail any more"
        assert "value=" not in match.group(0), (
            f"{field} renders a value; credential inputs must be write-only"
        )
        assert 'type="password"' in match.group(0), (
            f"{field} is a credential and must not render in the clear"
        )
