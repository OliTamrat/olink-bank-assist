# Deploy

**Normal path: merge to `main`.** There is no manual step.

1. CI (`.github/workflows/ci.yml`) runs ruff, mypy `--strict`, the full test
   suite, the golden-question evals, a migration round-trip, and a Docker
   build — on 3.11 and 3.12. CI runs **bare `pytest`**, not
   `python -m pytest`; the difference is real (`sys.path` does not include
   the repo root), so run bare `pytest` locally before claiming green.
2. On a CI-green push to `main`, `deploy.yml` builds, runs
   `alembic upgrade head` (bracketed by before/after revision logging), and
   deploys to Cloud Run. A merged migration is an applied migration.
3. Deploys are **queued, never cancelled** (`concurrency` group): Cloud Run
   uses optimistic concurrency on the service resource, and two simultaneous
   deploys make the loser fail with a version-conflict — a red X on a deploy
   that actually succeeded. The newest queued run still wins.

## Verify

`GET /health` on the service returns `{status, llm, llm_ready, revision}` —
`revision` carries the git SHA (`BANKASSIST_GIT_SHA`), which is how you
confirm the running code is the commit you merged.

## One-off redeploy

`deploy.yml` has `workflow_dispatch` — the "Run workflow" button. Use it for
a redeploy of the same code; never deploy from a laptop.

## The commands themselves

Live in `.github/workflows/deploy.yml` — deliberately not duplicated here.
If this page and that file disagree, the file is right.
