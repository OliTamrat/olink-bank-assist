"""Every function the browser pages call is defined in the page that calls it.

This exists because of an outage. The interface-strings work wrapped fifteen
translated labels in `esc(...)`, copying the pattern from `admin.html` — where
`esc` is defined. In `widget.html` it is not. One of those calls sits in the
"Searching official information…" indicator that runs on EVERY message, so the
customer's question appeared, the send handler threw `esc is not defined`, and
no reply ever rendered. It reached production.

Nothing caught it. The string table was well formed, the endpoints returned
correct answers, `mypy --strict` and 1,177 tests passed — because none of them
execute the page's JavaScript. The browser check that was run covered the
greeting and the language picker and never sent a message.

So this is the cheap general form of that lesson: parse the inline script,
collect every function called, and assert each one is defined in the same file
or is a browser built-in. It would have failed on the commit that broke chat.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGES = ["widget.html", "admin.html"]

# Things the browser provides. Deliberately short: a name that belongs here and
# is missing shows up as a failure with the name in it, which is a two-second
# fix, while a generous list quietly stops catching anything.
BUILTINS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "function",
    "new", "do", "else",
    "parseInt", "parseFloat", "isNaN", "encodeURIComponent",
    "decodeURIComponent", "fetch", "getComputedStyle", "setTimeout",
    "setInterval", "clearTimeout", "clearInterval", "alert", "confirm",
    "prompt", "btoa", "atob",
}


def _strip(js: str) -> str:
    """Remove comments and string literals.

    Without this the scan trips over ordinary prose — a comment reading "not
    yet (see below)" looks exactly like a call to `yet`.
    """
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    js = re.sub(r"(?m)//.*$", " ", js)
    js = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', js)
    js = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", js)
    return js


def _script(page: str) -> str:
    html = (Path("bankassist/static") / page).read_text(encoding="utf-8")
    return _strip("\n".join(re.findall(r"<script>(.*?)</script>", html, re.S)))


def _defined(script: str) -> set[str]:
    names = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", script))
    names |= set(re.findall(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=", script))
    # Parameters are locals a call site can legitimately use.
    for params in re.findall(r"function\s*[A-Za-z_$\w]*\s*\(([^)]*)\)", script):
        names |= {p.strip() for p in params.split(",") if p.strip()}
    return names


def _called(script: str) -> set[str]:
    # Bare calls only. A leading dot means it is a method on some object, whose
    # existence this cannot know and should not guess at.
    return set(re.findall(r"(?<![.\w$])([a-z_$][\w$]*)\s*\(", script))


@pytest.mark.parametrize("page", PAGES)
def test_every_function_called_is_defined(page: str) -> None:
    script = _script(page)
    missing = sorted(_called(script) - _defined(script) - BUILTINS)
    assert not missing, (
        f"{page} calls functions it does not define: {missing}. "
        "Either define them in this file or add genuine browser built-ins to "
        "BUILTINS — do not delete the assertion."
    )


def test_the_widget_defines_its_own_escaper() -> None:
    """The specific regression, named. `esc` interpolates the bank's display
    name into innerHTML, so the widget needs its own rather than borrowing the
    admin's by accident."""
    script = _script("widget.html")
    assert "esc" in _defined(script)


@pytest.mark.parametrize("page", PAGES)
def test_the_check_can_actually_fail(page: str) -> None:
    """A test that cannot fail is worse than no test. Feed the real scanner a
    call to something nothing defines and confirm it is reported."""
    script = _script(page) + "\n definitelyNotDefinedAnywhere();"
    missing = _called(script) - _defined(script) - BUILTINS
    assert "definitelyNotDefinedAnywhere" in missing
