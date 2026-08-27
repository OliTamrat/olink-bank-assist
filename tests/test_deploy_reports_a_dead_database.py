"""A deploy must not hide a database it could not reach.

On 2026-08-26 the production database was unreachable for **sixteen minutes**
during a deploy, and the log said this:

    Schema before: (Background on this error at: https://sqlalche.me/e/20/e3q8)

That is the last line of a Python traceback — a URL footer. It names nothing.
The step reported success, the deploy carried on, and the outage was only
noticed because somebody asked why one step was slow.

Three separate mechanisms had to line up for a total outage to render as one
inert line, and each is guarded below:

1. **A command substitution inside `echo`.** `echo "… $(cmd)"` makes the
   `echo` the command whose status counts, so `bash -e` never sees the
   failure. This file already carried a comment about exactly that trap, for
   the secret fetch two lines above.
2. **`tail -1` of a traceback.** The one line it keeps is the only line that
   never says what broke.
3. **No elapsed time.** Sixteen minutes and two seconds are the same log line
   without it, and the duration was the entire clue.

Guarded structurally, from the workflow's own text, because there is nothing
importable here — the same approach `test_create_admin.py` takes to the
bootstrap workflow. The replacement was driven for real against both a
healthy SQLite database and a refused Postgres connection; see the PR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"


def _code() -> str:
    """The step's shell with comment-only lines removed.

    These assertions are about what bash executes, not about the prose. The
    comments in that step quote the broken forms in order to explain them, so
    a naive substring search over the raw text finds the very patterns it is
    meant to forbid — which is how the first run of this file failed.
    """
    return "\n".join(
        line
        for line in _migration_step()["run"].splitlines()
        if not line.lstrip().startswith("#")
    )


def _migration_step() -> dict[str, Any]:
    # PyYAML resolves the bare `on:` key to True; irrelevant here, but the
    # same file is read that way elsewhere, so it is worth not being surprised.
    doc = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    steps = doc["jobs"]["deploy"]["steps"]
    for step in steps:
        if str(step.get("name", "")).startswith("Run database migrations"):
            return dict(step)
    raise AssertionError("the migration step is gone — this test is stale")


def test_the_schema_probe_is_not_swallowed_by_an_echo() -> None:
    """The exact shape that hid the outage."""
    run = _code()
    assert 'echo "Schema before: $(' not in run
    assert 'echo "Schema after:  $(' not in run


def test_the_reporter_is_called_directly_not_captured() -> None:
    """`$(schema_at)` would put the annotation and the error back inside a
    string, which is the same bug wearing the fix's clothes — and is what the
    first draft of the fix did."""
    run = _code()
    assert "schema_at " in run, "the helper must be called"
    assert "$(schema_at" not in run, (
        "capturing it swallows the ::warning:: and the traceback into one line"
    )


def test_the_failure_branch_is_reachable_under_set_e() -> None:
    """This step runs as `bash -e`, where a bare `out="$(cmd)"` whose
    substitution fails takes that exit status and kills the script on the
    spot — so a following `rc=$?` never runs and nothing is reported at all.
    Confirmed by running it against a refused connection: no output, exit 1.
    A command used as a condition is exempt.
    """
    run = _code()
    assert 'if out="$(python -m alembic current' in run, (
        "the assignment must be the if-condition, or set -e kills the "
        "function before it can report anything"
    )


def test_a_failure_is_announced_and_quotes_the_real_error() -> None:
    run = _code()
    assert "::warning::" in run, "an unreachable database must be annotated"
    assert "UNREACHABLE" in run
    assert 'printf \'%s\\n\' "$out" | tail -5' in run, (
        "one line of a traceback is the URL footer; the lines that name the "
        "fault are above it"
    )


def test_the_probe_does_not_fail_the_deploy_by_itself() -> None:
    """Deliberately non-fatal.

    `alembic upgrade head` on the next line opens its own connection and
    fails loudly if the database is still gone, which stops the deploy before
    Cloud Run is touched. A transient blip that has cleared by then should not
    fail a deploy that then works — which is exactly what happened on
    2026-08-26. The requirement is that it be SEEN, not that it stop the world.
    """
    run = _code()
    body = run[run.index("schema_at() {") : run.index("python -m alembic upgrade head")]
    assert "exit 1" not in body
    assert "python -m alembic upgrade head" in run


def test_it_reports_how_long_the_database_took() -> None:
    """The only clue that anything had happened at all."""
    run = _code()
    assert "SECONDS" in run
