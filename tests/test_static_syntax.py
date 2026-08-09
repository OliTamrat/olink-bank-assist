"""The panel's own JavaScript has to parse.

`admin.html` now carries well over a thousand lines of script. A stray quote in
any of it breaks the *entire* panel — not the one feature being edited — and
every Python test still passes, because the file is only ever served as bytes.
That happened while writing the audit page: a mismatched quote inside a string
of HTML, invisible to ruff, mypy and pytest alike.

Node is the checker because it is already on the runner for nothing else, and
`--check` parses without executing, so this cannot be tripped by code that
expects a browser.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from bankassist import agent

STATIC = Path(agent.__file__).parent / "static"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not available to parse the script"
)


def _inline_script(path: Path) -> str:
    blocks = re.findall(r"<script>\n(.*?)\n</script>", path.read_text(), re.S)
    assert blocks, f"no inline script found in {path.name}"
    return "\n".join(blocks)


def _check(source: str, label: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
        handle.write(source)
        temp = Path(handle.name)
    try:
        result = subprocess.run(
            ["node", "--check", str(temp)], capture_output=True, text=True
        )
    finally:
        temp.unlink()
    assert result.returncode == 0, f"{label} does not parse:\n{result.stderr}"


@pytest.mark.parametrize("page", ["admin.html", "widget.html"])
def test_the_inline_script_parses(page: str) -> None:
    _check(_inline_script(STATIC / page), page)


def test_the_embed_loader_parses() -> None:
    """This one runs on a bank's own production pages.

    A syntax error here is a script error in someone else's console, on their
    site, attributed to us.
    """
    _check((STATIC / "embed.js").read_text(), "embed.js")


def test_the_logo_layout_hook_targets_an_element_that_exists() -> None:
    """A `closest()` for a selector nothing matches fails silently.

    The widget's rule was written as `.head[data-logo="wide"]` against markup
    whose element is a bare `<header>`. Nothing errored — `closest` returned
    null, the attribute landed on the tile instead, and a bank's name simply
    stayed printed twice beside a logo that already contained it. The CSS
    selector and the JS lookup have to name the same thing, and that thing has
    to be in the document.
    """
    import re
    from pathlib import Path

    from bankassist import agent

    static = Path(agent.__file__).parent / "static"
    for name, marker in (("widget.html", "header"), ("admin.html", "side-brand")):
        src = (static / name).read_text()
        hooks = set(re.findall(r'closest\("([^"]+)"\)', src))
        assert hooks, f"{name} no longer measures the logo's shape"
        for sel in hooks:
            bare = sel.lstrip(".")
            assert (f'class="{bare}"' in src or f"<{bare}" in src
                    or f'class="{bare} ' in src or f' {bare}"' in src), (
                f"{name}: closest({sel!r}) matches nothing in the markup"
            )
        assert f'{marker}[data-logo=' in src or f'.{marker}[data-logo=' in src, (
            f"{name}: the data-logo rule no longer hangs off {marker}"
        )


def test_the_opening_screen_is_cleared_when_a_conversation_starts() -> None:
    """The welcome block is built once and removed by `ask()`.

    If a new entry point forgets to clear it — or the class is renamed on one
    side only — nothing errors. The opening screen simply stays pinned above
    the thread, so every reply appears underneath a greeting and three
    still-tappable openers. It looks like a layout quirk rather than a bug,
    which is exactly why it would survive review.
    """
    import re
    from pathlib import Path

    from bankassist import agent

    src = (Path(agent.__file__).parent / "static" / "widget.html").read_text()
    assert 'el("div", "welcome")' in src, "the opening screen is gone"

    removals = re.findall(r'querySelectorAll\("([^"]*)"\)', src)
    assert any("welcome" in sel for sel in removals), (
        "nothing removes .welcome — the opening screen would stay above the thread"
    )
