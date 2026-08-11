# Refreshing "Ask OKM"

Implements ADR-0015. Two steps, run wherever both repos and the production
database are reachable — not from an agent sandbox, same boundary as
`scripts/faq_export.py` and `scripts/prune_merged_branches.py`.

## 1. Materialise the portal's content

In a checkout of `olink-knowledge`:

```bash
pip install -r requirements.txt
python scripts/sync_docs.py   # needs git access to the 7 product repos
```

This writes `content/<product>/**/*.md` — the same tree the portal itself
builds from.

## 2. Ingest it

In a checkout of `olink-bank-assist`, against the database you want to
update (production: the `BANKASSIST_DATABASE_URL` secret in Secret Manager;
local: whatever `.env` already points at):

```bash
python -m bankassist.seed_okm --source /path/to/olink-knowledge/content
```

Prints `N files seen, M created, K updated`. Re-running is always safe —
see ADR-0015 for why a re-run replaces by title rather than duplicating.

## Verify

```bash
python -m bankassist.show_token okm   # the okm tenant's admin token
```

Open the widget at `/?bank=okm` (or the admin panel) and ask something the
fleet's docs actually answer — e.g. "why does olink-dispatch never draft a
reply that accepts a rate?" should come back sourced from
`dispatch/decisions/0003-no-rate-commitments.md` (or wherever that ADR now
lives), not from general knowledge, because `allow_general_knowledge` is off
for this tenant.

## Automating it (not yet wired up)

Once a fine-grained PAT exists with read-only *Contents* access to
`olink-knowledge` and all seven product repos (the same shape as
`olink-knowledge`'s own `OKM_SYNC_TOKEN`), add it as a `bankassist` repo
secret named `OKM_SYNC_TOKEN` and drop this in as
`.github/workflows/refresh-okm.yml`:

```yaml
name: Refresh Ask OKM

on:
  workflow_dispatch: {}

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: OliTamrat/olink-knowledge
          path: olink-knowledge
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Sync product docs
        working-directory: olink-knowledge
        env:
          OKM_SYNC_TOKEN: ${{ secrets.OKM_SYNC_TOKEN }}
        run: |
          pip install -r requirements.txt
          python scripts/sync_docs.py
      - uses: actions/checkout@v4
        with:
          path: olink-bank-assist
      - name: Ingest
        working-directory: olink-bank-assist
        env:
          GCP_PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}
        run: |
          pip install .
          DB_URL="$(gcloud secrets versions access latest --secret=bankassist-database-url --project="$GCP_PROJECT_ID")" \
            || { echo "::error::could not read bankassist-database-url"; exit 1; }
          export BANKASSIST_DATABASE_URL="$(printf '%s' "$DB_URL" | sed '1s/^\xef\xbb\xbf//' | tr -d '[:space:]')"
          python -m bankassist.seed_okm --source ../olink-knowledge/content
```

(Needs `google-github-actions/auth` + `setup-gcloud` steps ahead of the
`gcloud secrets versions access` call — copy the pattern from `deploy.yml`
rather than duplicating it here, since that file is the one this doc already
says wins on disagreement.) A daily schedule (`schedule: - cron: "30 4 * * *"`,
after `olink-knowledge`'s own 04:00 UTC sync) would keep it current with no
manual step at all, once the PAT exists.
