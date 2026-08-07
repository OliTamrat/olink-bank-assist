# Deploying to Cloud Run

The one-time GCP/Supabase bootstrapping below (project, billing, service
account, Secret Manager) has to be done once by a human with `gcloud`
credentials — this sandbox has neither, and that first trust boundary can't
be delegated to CI. **Everything after that is fully automated**:
`.github/workflows/deploy.yml` builds the image, runs Alembic migrations,
seeds every tenant, deploys to Cloud Run, and points `APP_BASE_URL` at the
live URL — all on every push to `main` that passes CI, and on demand via
Actions → Deploy to Cloud Run → Run workflow. No local Docker, no local
Python, no manual seeding step, ever again after the two GitHub secrets
below are set once.

## Decisions

1. **GCP project: decided and done.** `olink-bank-assist` — a new, dedicated
   project rather than folding into `olink-dispatch`'s, for clean billing
   and IAM isolation on a new product from day one — same reasoning as the
   separate Supabase project below, and the separate GitHub repo this
   product already lives in.
2. **Postgres: decided and done.** A **new, separate Supabase project**
   dedicated to bank-assist — never pointed at `olink-dispatch`'s database.
   Bank Assist's tables hold sourced content about three real, named banks
   (CBE, Dashen, Awash); it must not sit next to trucking-fleet data in the
   same project, share a connection pool with it, or be reachable through
   it in any way. Uses the **pooled** connection string (port 6543,
   "Transaction" mode) — Cloud Run's request-scoped connections suit a
   pooler better than a direct connection (port 5432). This app uses
   **psycopg2** (sync SQLAlchemy), not asyncpg — psycopg2 doesn't do the
   automatic server-side prepared-statement caching that breaks under
   pgBouncer transaction mode, so the `statement_cache_size=0` fix
   documented in olink-dispatch's CLAUDE.md (an asyncpg-specific gotcha)
   does not apply here. If prepared-statement/pooling errors ever show up
   in production logs, the standard fallback is the direct connection
   string (port 5432).

## One-time GCP setup (done once, by a human)

```bash
export PROJECT_ID="olink-bank-assist"
export REGION="us-east1"

gcloud projects create "$PROJECT_ID" --name="Olink Bank Assist"
gcloud billing accounts list
gcloud billing projects link "$PROJECT_ID" --billing-account="YOUR_BILLING_ACCOUNT_ID"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com

gcloud artifacts repositories create bankassist \
  --repository-format=docker --location="$REGION" \
  --description="Olink Bank Assist images"

# A deploy-only service account — NOT project owner/editor. Scoped to
# exactly what the GitHub Actions workflow needs: push images, deploy
# Cloud Run, act as itself, and read secrets.
gcloud iam service-accounts create bankassist-deployer \
  --display-name="Bank Assist CI/CD deployer"

export SA="bankassist-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

for ROLE in roles/run.admin roles/artifactregistry.writer \
            roles/iam.serviceAccountUser roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA}" --role="$ROLE"
done

gcloud iam service-accounts keys create bankassist-deployer-key.json \
  --iam-account="$SA"
# ^ Treat this file as a secret. Copy its contents into the GitHub repo
#   secret GCP_SA_KEY below, then delete the local copy.

# The one secret Cloud Run reads at startup, never baked into the image or
# the workflow file. Gemini is optional — the app runs in extractive mode
# without it; add a GEMINI_API_KEY secret and wire it back into
# deploy.yml's --set-secrets later if conversational answers are wanted.
echo -n "postgresql://...(the bank-assist Supabase project's pooled connection string, port 6543)..." | \
  gcloud secrets create bankassist-database-url --data-file=-
```

## Wire up auto-deploy (the only remaining manual step)

In the GitHub repo → Settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `GCP_SA_KEY` | full contents of `bankassist-deployer-key.json` |
| `GCP_PROJECT_ID` | `olink-bank-assist` |

That's it — no `CLOUD_RUN_HOSTNAME` secret needed. `deploy.yml` discovers
the Cloud Run URL itself right after deploying and sets `APP_BASE_URL`
automatically, so it stays correct even if the service is ever recreated.

From here, every push to `main` that passes CI: builds the image, runs
`alembic upgrade head`, re-seeds every tenant (`seed`, `seed_cbe`,
`seed_dashen`, `seed_awash` — all idempotent, skip banks that already
exist), deploys to Cloud Run, and points `APP_BASE_URL` at the live URL.
Trigger a one-off run anytime via Actions → Deploy to Cloud Run → Run
workflow — no local `gcloud`/Docker/Python required for any of it.

## Live

**`https://bankassist-430565798339.us-east1.run.app`** — deployed 2026-08-07,
all four tenants (`demo`, `cbe`, `dashen`, `awash`) seeded.

```bash
curl https://bankassist-430565798339.us-east1.run.app/health
# {"status":"ok","llm":"gemini"|"extractive-fallback"}
```

- `/widget?bank=cbe` — the link you hand a prospect instead of demoing off a
  laptop. Swap the slug for `dashen`, `awash`, or `demo`.
- `/admin` — asks for a bank slug and that tenant's admin token.
- There is deliberately **no route at `/`**, so the root returns
  `{"detail":"Not Found"}`. That is FastAPI answering — i.e. the service is up.

### Admin tokens

The seed scripts no longer print tokens under CI — they used to land in the
GitHub Actions log on every deploy, readable by anyone with repo access and
retained by GitHub. Retrieve one from a machine that can reach the database:

```bash
python -m bankassist.show_token cbe
python -m bankassist.show_token cbe --rotate   # if a token has been exposed
```

## Runtime identity — known tradeoff

`deploy.yml` pins `bankassist-deployer` as the Cloud Run **runtime** service
account as well as the CI deployer. Cloud Run otherwise defaults a revision to
the project's generic Compute Engine default SA, which has no `secretAccessor`
and so cannot read `bankassist-database-url` — the revision then fails to start
even though the `gcloud run deploy` command itself reports success.

Reusing the deployer SA fixed that with no extra manual setup, but it gives the
running service more privilege than it needs (it can deploy Cloud Run and write
to Artifact Registry). Worth splitting into a dedicated runtime SA holding only
`secretmanager.secretAccessor`:

```bash
gcloud iam service-accounts create bankassist-runtime \
  --display-name="Bank Assist Cloud Run runtime"
gcloud secrets add-iam-policy-binding bankassist-database-url \
  --member="serviceAccount:bankassist-runtime@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
# then swap the --service-account value in deploy.yml
```
