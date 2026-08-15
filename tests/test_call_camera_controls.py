"""A live camera always has an off switch.

Reported from a real call on the live demo (2026-08-15). The customer was on
an **audio** call, pressed "Show my ID", and:

* the teller's dashboard showed the video — so the camera was genuinely on;
* the customer's own screen read "Your camera is not available — read the
  number on your ID to the teller instead";
* and there was no control anywhere that turned it off again.

Three symptoms, and the same root: the camera's controls were driven by what
the customer CHOSE at the start of the call rather than by what the camera is
actually doing now. On `media === "audio"` the camera button is hidden, the ID
button hides itself once the camera is on, and the only path back to audio ran
through a timer that a half-failed start never set.

`setCameraEnabled(true)` can reject with the track already published — a
publish timeout, a slow first grant on iOS — and the old code took that
rejection as proof the camera was off. It then told the customer so, in a
sentence contradicted by what the teller was looking at.

Reproduced and fixed by driving the real widget in Chromium with a stubbed
LiveKit whose first enable turns the camera on *and* rejects: on `main` there
was no off switch and pressing anything left the camera live; with the fix the
camera button appears and turns it off. These assertions pin the four
properties that made the difference, so a later tidy-up cannot quietly
reintroduce "the session type says this cannot be happening".

Source-level on purpose: this logic lives inside the widget's IIFE with no
seam to import, and CI has no browser. `tests/test_static_pages.py` runs
`node --check` over the same file, so a broken edit fails there rather than
passing here.
"""

from __future__ import annotations

import re
from pathlib import Path

WIDGET = (
    Path(__file__).resolve().parent.parent / "bankassist" / "static" / "widget.html"
).read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Whitespace-normalised, so an assertion survives a re-wrap."""
    return " ".join(text.split())


def test_the_camera_button_is_shown_whenever_the_camera_is_on() -> None:
    """The exit hatch. `session.media` says what was asked for at the start;
    it does not say whether a camera is publishing right now, and only the
    second question may decide whether an off switch is on screen."""
    assert "var hasCam = chose || camOn;" in _flat(WIDGET), (
        "the camera control's visibility must include the camera actually "
        "being on — keyed on session.media alone, an audio call that ends up "
        "publishing video has no way to stop"
    )


def test_the_id_button_stops_a_camera_that_is_already_on() -> None:
    """A running timer is not the only way the camera can be on. If the start
    half-succeeded, `idTimer` is null while the camera publishes — and the old
    `if (idTimer)` test sent the customer back through startIdShare, turning an
    already-on camera on again. From the customer's side: a dead button."""
    handler = re.search(
        r'getElementById\("btnId"\)\.addEventListener\("click",(.{0,900}?)\}\);',
        WIDGET,
        re.S,
    )
    assert handler, "the ID button's click handler moved — update this test"
    body = _flat(handler.group(1))
    assert "isCameraEnabled" in body, (
        "the ID button must decide from whether the camera is on, not only "
        "from whether its own countdown is running"
    )
    assert "stopIdShare()" in body


def test_a_failed_start_does_not_report_a_camera_that_is_running() -> None:
    """The rejection handler is `then`'s second argument, never a trailing
    `.catch()`. A `.catch()` there also swallows anything thrown by the success
    handler, so one broken line in the block that runs when the camera came on
    reports "your camera is not available" about a live camera."""
    start = WIDGET.index("function startIdShare()")
    end = WIDGET.index("getElementById(\"btnId\").addEventListener", start)
    body = _flat(WIDGET[start:end])
    assert "setCameraEnabled(true).then(function () {" in body
    assert ".catch(function" not in body, (
        "startIdShare must pass its failure handler to then(ok, fail); a "
        "trailing .catch() cannot tell a camera that failed to start from a "
        "camera that started and then hit a bug on the next line"
    )
    assert "paintControls();" in body.split("Your camera is not available")[1], (
        "after a failed start the controls must be repainted from what is "
        "actually true — the camera may be publishing regardless"
    )


def test_stopping_an_id_share_leaves_an_audio_call_audio() -> None:
    """`camWasOn` is only a reason to LEAVE the camera on when the customer
    asked for video in the first place. A first attempt that failed with the
    camera on made `camWasOn` true for the second, which turned the restore
    into a reason never to turn it off at all."""
    start = WIDGET.index("function stopIdShare()")
    body = _flat(WIDGET[start : WIDGET.index("function startIdShare()", start)])
    assert 'camWasOn && session && session.media === "video"' in body, (
        "stopping the share must return an audio call to audio, whatever a "
        "previous failed attempt left camWasOn holding"
    )


def test_the_stale_failure_message_is_cleared_when_the_camera_starts() -> None:
    """A first press that failed left "your camera is not available" on screen
    and nothing ever took it down, so the customer read it while the teller
    was looking at their face."""
    start = WIDGET.index("function startIdShare()")
    ok_block = WIDGET[start : WIDGET.index("idTimer = setInterval", start)]
    assert 'callStatus("")' in _flat(ok_block), (
        "a successful ID share must clear whatever the previous attempt said"
    )


def test_turning_the_camera_off_by_hand_ends_the_id_countdown() -> None:
    """Otherwise a countdown keeps running for a camera that is already off,
    and fires a minute later at a camera the customer had meanwhile turned
    back on deliberately."""
    handler = re.search(
        r'getElementById\("btnCam"\)\.addEventListener\("click",(.{0,600}?)\}\);',
        WIDGET,
        re.S,
    )
    assert handler, "the camera button's click handler moved — update this test"
    body = _flat(handler.group(1))
    assert "idTimer" in body and "stopIdShare()" in body, (
        "turning the camera off by hand must also end an ID share"
    )
