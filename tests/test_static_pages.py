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

**It then let a second one through, which is why it resolves scopes.** The
first version collected every `var name = ...` and every parameter anywhere in
the file into one flat set of "defined" names. So `svg("check")` and
`el("div")` — helpers that exist in the widget and not in the admin — passed,
because `admin.html` happens to contain `var el = $("gate-err")` and
`var svg = document.querySelector(".chart")` as *locals inside unrelated
functions*. Both would have thrown the moment a toast rendered.

A flat set cannot tell a global helper from someone else's local, so this
walks the scope chain instead: each `function`/arrow body is a scope holding
its parameters and the declarations inside it, and a call resolves outward
from where it sits. Borrowing a name from a sibling function is now a failure,
which is what it always was at runtime.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

PAGES = ["widget.html", "admin.html", "site.html"]

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


_FUNC = re.compile(r"function\s*([A-Za-z_$][\w$]*)?\s*\(([^)]*)\)\s*{")
_ARROW = re.compile(r"(?:\(([^)]*)\)|([A-Za-z_$][\w$]*))\s*=>\s*{")
_DECL = re.compile(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)")
_CALL = re.compile(r"(?<![.\w$])([a-z_$][\w$]*)\s*\(")


class Scope:
    """A function body: where it starts, where it ends, what it can see."""

    def __init__(self, start: int, end: int, names: set[str]) -> None:
        self.start, self.end, self.names = start, end, names

    def holds(self, pos: int) -> bool:
        return self.start <= pos <= self.end


def _closing(script: str, brace: int) -> int:
    """Index of the `}` matching the `{` at `brace`.

    Sound only because `_strip` has already removed the two things that would
    otherwise put a stray brace in the way: comments and string literals.
    """
    depth = 0
    for i in range(brace, len(script)):
        if script[i] == "{":
            depth += 1
        elif script[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(script)


def _scopes(script: str) -> list[Scope]:
    """Every function body in the file, plus the file itself.

    Only functions open a scope, not blocks. That is exactly right for `var`,
    which hoists to the enclosing function, and close enough for the `let` and
    `const` in these pages — erring towards permissive, so a failure here is
    always a real one.
    """
    scopes = [Scope(0, len(script), set())]
    for m in _FUNC.finditer(script):
        body = m.end() - 1
        raw = m.group(2) or ""
        scopes.append(
            Scope(body, _closing(script, body), {p.strip() for p in raw.split(",") if p.strip()})
        )
    for m in _ARROW.finditer(script):
        body = m.end() - 1
        raw = m.group(1) if m.group(1) is not None else (m.group(2) or "")
        scopes.append(
            Scope(body, _closing(script, body), {p.strip() for p in raw.split(",") if p.strip()})
        )

    def innermost(pos: int) -> Scope:
        return min((s for s in scopes if s.holds(pos)), key=lambda s: s.end - s.start)

    # A declaration belongs to the tightest function around it; a named
    # function declaration belongs to the scope that can call it.
    for d in _DECL.finditer(script):
        innermost(d.start()).names.add(d.group(1))
    for m in _FUNC.finditer(script):
        if m.group(1):
            innermost(m.start()).names.add(m.group(1))
    return scopes


def _unresolved(script: str) -> set[str]:
    """Names called where nothing of that name is in scope."""
    scopes = _scopes(script)
    missing = set()
    for call in _CALL.finditer(script):
        name = call.group(1)
        if name in BUILTINS:
            continue
        chain = [s for s in scopes if s.holds(call.start())]
        if not any(name in s.names for s in chain):
            missing.add(name)
    return missing


def _defines(script: str, name: str) -> bool:
    """Anywhere in the file. Deliberately not "at the top level" — `widget.html`
    wraps its whole script in an IIFE, so it has no top level to speak of."""
    return any(name in s.names for s in _scopes(script))


@pytest.mark.parametrize("page", PAGES)
def test_every_function_called_is_defined(page: str) -> None:
    missing = sorted(_unresolved(_script(page)))
    assert not missing, (
        f"{page} calls functions it does not define: {missing}. "
        "Either define them in this file or add genuine browser built-ins to "
        "BUILTINS — do not delete the assertion."
    )


def test_the_widget_defines_its_own_escaper() -> None:
    """The specific regression, named. `esc` interpolates the bank's display
    name into innerHTML, so the widget needs its own rather than borrowing the
    admin's by accident."""
    assert _defines(_script("widget.html"), "esc")


@pytest.mark.parametrize("page", PAGES)
def test_the_check_can_actually_fail(page: str) -> None:
    """A test that cannot fail is worse than no test. Feed the real scanner a
    call to something nothing defines and confirm it is reported."""
    script = _script(page) + "\n definitelyNotDefinedAnywhere();"
    assert "definitelyNotDefinedAnywhere" in _unresolved(script)


def test_a_name_cannot_be_borrowed_from_another_function() -> None:
    """The false negative that let `svg()` and `el()` through, in miniature.

    `admin.html` holds `var el = ...` and `var svg = ...` as locals inside
    unrelated functions. A flat set of names treated those as definitions, so
    calling them from a new function passed the check and threw in the
    browser. Written against a synthetic script rather than the real pages so
    it keeps testing this the day someone promotes `el` to a real helper.
    """
    script = _strip(
        """
        function one() { var el = document.getElementById("x"); el.remove(); }
        function two() { el("div"); }
        """
    )
    assert "el" in _unresolved(script), "a sibling function's local is not in scope"

    hoisted = _strip(
        """
        function el(tag) { return document.createElement(tag); }
        function two() { el("div"); }
        """
    )
    assert "el" not in _unresolved(hoisted), "a real helper must still resolve"


# ------------------------------------------------------- loading a file
#
# The importers were paste-only, and that is fine on a laptop with the page
# open beside you. It is unusable everywhere else: the realistic way a bank's
# FAQ arrives is a PDF somebody printed, and the text pulled out of it is
# fifty thousand characters. Nobody selects that inside a phone textarea — and
# the first person who tried was handed a .txt file for a form that could not
# accept one.


@pytest.mark.parametrize("field", ["fi-file", "imp-file"])
def test_both_importers_take_a_file(field: str) -> None:
    """The FAQ importer and the page importer have the same problem and get
    the same answer."""
    html = (Path("bankassist/static") / "admin.html").read_text(encoding="utf-8")
    assert f'id="{field}"' in html
    assert "wireFilePicker" in html


def test_the_file_is_read_in_the_browser() -> None:
    """FileReader rather than an upload endpoint. The text lands in the same
    box and goes through the same preview and commit, so this adds a
    convenience without adding a route, a stored file, or a size limit that
    has to be enforced somewhere else as well."""
    html = (Path("bankassist/static") / "admin.html").read_text(encoding="utf-8")
    assert "new FileReader()" in html
    assert "readAsText" in html
    # No upload route was added for this.
    assert "multipart/form-data" not in html


def test_an_oversized_file_is_refused_not_truncated() -> None:
    """A half-read FAQ that imports ninety of a hundred and sixty questions is
    worse than one that refuses, because nobody counts the ones that never
    arrived."""
    html = (Path("bankassist/static") / "admin.html").read_text(encoding="utf-8")
    assert "MAX_IMPORT_FILE" in html
    block = html.split("function wireFilePicker")[1].split("function faqImportForm")[0]
    assert "too big to read here" in block
    assert "picker.value = \"\"" in block


# ------------------------------------------------------------ confirmations
#
# "Whenever I get a confirmation the small modal window that tells confirmed,
# created or updated on the top is pretty ugly, sometimes unviewable." It was
# 12.5px muted text in the topbar: a successful import of a hundred and sixty
# questions and a failed save rendered identically, in the one strip of the
# page nobody looks at after the first minute.
#
# The clarification matters as much as the complaint — "not a text size, I
# don't want you to oversize it; the toast design and where it displays is the
# issue" — so these pin placement, dismissal and the success/failure
# distinction, and deliberately do not pin the font size upwards.


def _admin() -> str:
    return (Path("bankassist/static") / "admin.html").read_text(encoding="utf-8")


def test_confirmations_are_not_topbar_text_any_more() -> None:
    html = _admin()
    assert 'id="status"' not in html, "the old status line is what this replaced"
    assert 'id="toasts"' in html


def test_a_toast_dismisses_itself_within_ten_seconds() -> None:
    """'Display for about 10 seconds max and disappear.' Nothing may sit there
    waiting to be clicked away, and nothing may outstay ten seconds."""
    script = _script("admin.html")
    block = script.split("var TOAST_MS")[1].split("}")[0]
    waits = [int(n) for n in re.findall(r":\s*(\d+)", block)]
    assert waits, "TOAST_MS must set a lifetime per kind"
    assert max(waits) <= 10_000, f"a toast outstays ten seconds: {waits}"
    assert min(waits) >= 3_000, f"too fast to finish reading: {waits}"
    assert "setTimeout" in _admin().split("function setStatus")[1][:1200]


def test_failures_look_different_from_confirmations() -> None:
    """The substance of the complaint. Twenty-one call sites report an error;
    if they render like a success the card is prettier and no more useful."""
    html = _admin()
    assert html.count('setStatus(e.message, "error")') >= 20
    assert 'setStatus(err.message, "error")' in html
    # Neither kind may be left to the default.
    assert '.toast.ok' in html and '.toast.bad' in html


def test_no_call_site_reports_a_failure_as_neutral() -> None:
    """A missed `"error"` is invisible in review — it just renders grey. So
    assert it directly: anything carrying an exception says so."""
    leaked = [
        line.strip()
        for line in _admin().splitlines()
        if re.search(r"setStatus\([^)]*\.message", line) and '"error"' not in line
    ]
    assert not leaked, f"these report an exception without marking it a failure: {leaked}"


def test_the_toast_escapes_what_it_renders() -> None:
    """It builds innerHTML, and the text can be a server error message. The
    widget outage came from assuming an escaper existed; here it must be used
    as well as defined."""
    block = _admin().split("function setStatus")[1].split("function dismissToast")[0]
    assert "esc(text)" in block
    assert "innerHTML = text" not in block


def test_clearing_still_works_on_page_change() -> None:
    """go() calls setStatus("") on every navigation. That contract predates
    the toast and is why a confirmation does not follow you to another screen."""
    block = _admin().split("function setStatus")[1].split("function dismissToast")[0]
    assert "if (!text)" in block
    assert 'setStatus("")' in _admin()


def test_the_toast_host_survives_the_shell_being_hidden() -> None:
    """Found by driving the page, not by reading it.

    A request that fails on an expired session hides `#shell` and reports
    "Signed out". With the host inside the shell, that message was written to
    an element that had just been display:none'd — the one confirmation a
    dispatcher most needs was the one guaranteed not to appear. It is a
    `position: fixed` element; it belongs to the document, not to a screen.
    """
    html = _admin()
    # Anchored to the line, not the substring — the comment above the host
    # quotes the tag, and splitting on it landed mid-sentence.
    body = re.split(r"(?m)^<body>$", html)[1]
    host = body.index('id="toasts"')
    shell = body.index('id="shell"')
    gate = body.index('id="gate"')
    assert host < shell and host < gate, (
        "the toast host must precede both the gate and the shell, so neither "
        "hiding one can take the confirmations with it"
    )


@pytest.mark.parametrize("page", PAGES)
def test_no_stylesheet_reaches_for_a_colour_that_does_not_exist(page: str) -> None:
    """`var(--text)` on a page whose token is `--ink` is invisible in review.

    CSS does not complain: an undefined custom property with no fallback makes
    the declaration behave as `unset`, so `color` quietly inherits and usually
    looks right. It cost three real bugs here — the toast's own text colour,
    the file picker's hover, and a pair of escalation-desk rules that kept a
    hard-coded red through a switch to the light theme because a fallback was
    masking the same typo.
    """
    css = "\n".join(
        re.findall(
            r"<style>(.*?)</style>",
            (Path("bankassist/static") / page).read_text(encoding="utf-8"),
            re.S,
        )
    )
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    used = set(re.findall(r"var\(\s*(--[\w-]+)", css))
    missing = sorted(used - defined)
    assert not missing, (
        f"{page} references custom properties nothing defines: {missing}. "
        "A fallback does not make this fine — it pins one theme's colour."
    )


# ------------------------------------------------------------ it parses
#
# The scanner above is regex over source text, so it reads a BROKEN file just
# as happily as a working one. Wiring the teller console up to the string
# table swallowed the opening quote of a literal and left its closing quote
# behind, so a line ended mid-string — and every check in this file passed. The
# page did not load at all: one syntax error takes the whole panel down, sign-in
# included.
#
# node is present in this environment, and `--check` parses without executing,
# so it needs none of the browser globals these files depend on.


def _node() -> str | None:
    return shutil.which("node")


@pytest.mark.parametrize("page", PAGES)
def test_the_page_is_syntactically_valid_javascript(page: str) -> None:
    node = _node()
    if node is None:
        pytest.skip("node is not on PATH here; CI has it")
    html = (Path("bankassist/static") / page).read_text(encoding="utf-8")
    # The real source, not the stripped copy — a stripped file has had its
    # string literals replaced and would parse even when the original cannot.
    js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    with tempfile.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(js)
        path = fh.name
    try:
        result = subprocess.run(
            [node, "--check", path], capture_output=True, text=True, timeout=30
        )
    finally:
        os.unlink(path)
    assert result.returncode == 0, f"{page} does not parse:\n{result.stderr}"


def test_the_syntax_check_can_actually_fail() -> None:
    """The same file with one quote removed must be reported."""
    node = _node()
    if node is None:
        pytest.skip("node is not on PATH here; CI has it")
    with tempfile.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as fh:
        fh.write('var a = "unterminated\nvar b = 1;\n')
        path = fh.name
    try:
        result = subprocess.run(
            [node, "--check", path], capture_output=True, text=True, timeout=30
        )
    finally:
        os.unlink(path)
    assert result.returncode != 0
