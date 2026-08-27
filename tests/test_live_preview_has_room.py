"""The Live Preview card has to be tall enough to show a conversation.

Reported from a phone: the chat window is "too tight or short, you can't see
the chat conversation unless you scroll up and down".

The frame was a flat `360px` at every width. The widget inside it is a column
— disclaimer, header, the conversation, composer — and only the conversation
flexes, so every pixel the fixed parts take is a pixel the conversation loses.
The fixed parts are exactly the ones that grow as the screen narrows. Measured
inside the frame, driving the real panel in Chromium:

                        desktop (1139px)   phone (325px)
    disclaimer               34px             84px   (wraps to three lines)
    header                   68px             68px
    composer + note          94px            123px   (the note wraps)
    ----------------------------------------------------------------
    left for the chat       164px             84px   of 378px of content

84px is one bubble. The card whose entire job is showing a bank its assistant
working showed a sliver of one message and hid 78% of the exchange.

After: the phone frame is 608px and the chat area 332px, with 46px hidden
instead of 294px. Desktop is deliberately unchanged — it measured 18px hidden,
which is fine, and it is not what was reported.

Two properties below are regression guards for mistakes already made once
each, and the second was made *again* while writing this fix.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = (ROOT / "bankassist" / "static" / "admin.html").read_text(encoding="utf-8")

CLAMP = re.compile(r"\.preview \.frame \{[^}]*height:\s*clamp\(\s*(\d+)px,[^)]*\)")
BASE = re.compile(r"\.preview \.frame \{[^}]*height:\s*(\d+)px")


def test_a_narrow_screen_gets_a_taller_frame() -> None:
    assert CLAMP.search(ADMIN_HTML), (
        "without this the phone frame stays at 360px, of which 275px is the "
        "widget's own chrome"
    )


def test_the_override_comes_after_the_rule_it_overrides() -> None:
    """The cascade, and the reason this test exists rather than a comment.

    Both selectors are `.preview .frame`, so specificity is equal and source
    order decides. The first attempt put the override in the `max-width: 980px`
    block near the top of the stylesheet — above the base declaration — and it
    silently lost: the browser reported the frame still 360px on a phone.

    A media query is not a specificity boost. The drawer shipped without an
    opener for precisely this reason (PR #177), which makes this the second
    time, so it is asserted rather than remembered.
    """
    base = BASE.search(ADMIN_HTML)
    clamp = CLAMP.search(ADMIN_HTML)
    assert base and clamp
    assert clamp.start() > base.start(), (
        "the narrow-screen height must be declared after the default one, or "
        "equal specificity lets the default win and the override does nothing"
    )


def test_the_floor_is_never_below_the_desktop_height() -> None:
    """A phone in landscape is ~390px TALL and matches `max-width: 980px`.

    A bare `72vh` there is 281px — shorter than the 360px it replaces, so the
    fix would have made the reported problem worse on a rotated phone. The
    `clamp` floor keeps that case exactly as it was.
    """
    base = BASE.search(ADMIN_HTML)
    clamp = CLAMP.search(ADMIN_HTML)
    assert base and clamp
    assert int(clamp.group(1)) >= int(base.group(1)), (
        "the clamp floor must not be shorter than the default height, or a "
        "landscape phone gets less room than before"
    )


def test_the_ceiling_exists() -> None:
    """Unbounded `vh` turns one card into a page of its own on a tablet."""
    clamp = re.search(r"height:\s*clamp\([^)]*,\s*(\d+)px\s*\)", ADMIN_HTML)
    assert clamp is not None, "clamp needs a maximum, not just a floor"


def test_the_widget_still_gives_its_chat_the_leftover_height() -> None:
    """The other half of the mechanism, in the other file.

    Making the frame taller only helps because `#chat` is the flexing child.
    If it ever stops being one, a taller frame adds empty space under the
    composer and the conversation stays exactly as cramped.
    """
    widget = (ROOT / "bankassist" / "static" / "widget.html").read_text(encoding="utf-8")
    chat = re.search(r"#chat \{[^}]*\}", widget)
    assert chat is not None
    assert "flex: 1" in chat.group(0)
    assert "overflow-y: auto" in chat.group(0)
