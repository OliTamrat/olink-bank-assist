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
