# Deploying to Cloud Run

This sandbox has no `gcloud` CLI and no GCP credentials, so the steps below
are written for **you to run once from your own machine** (where you
already have `gcloud` authenticated against your Olink projects). After
that one-time setup, `.github/workflows/deploy.yml` auto-deploys on every
push to `main` that passes CI — no manual steps after today.

## Decisions needed before you start

1. **Which GCP project?** A new dedicated `bank-assist` project, or reuse
   an existing Olink project (e.g. the one `olink-dispatch` runs in)? A
   dedicated project is cleaner for billing/IAM isolation on a new product;
   reusing one is faster. Either works — the commands below are the same,
   just substitute `$PROJECT_ID`.
2. **Postgres: decided.** Use your existing Olink Supabase **organization**
   (same account, `olink-dispatch` already lives there) but create a **new,
   separate Supabase project** dedicated to bank-assist — never point at
   `olink-dispatch`'s database. Bank Assist's tables hold sourced content
   about three real, named banks (CBE, Dashen, Awash); it must not sit next
   to trucking-fleet data in the same project, share a connection pool
   with it, or be reachable through it in any way. Steps:
   1. [supabase.com/dashboard](https://supabase.com/dashboard) → your
      existing Olink organization → **New project**.
   2. Name it `bank-assist` (or similar), pick a region close to your
      Cloud Run region (`us-east1` below → pick a Supabase US region),
      set a strong database password, create.
   3. Once provisioned: **Project Settings → Database → Connection
      string** → copy the **URI** form (not the psql command). It looks
      like `postgresql://postgres.[ref]:[password]@aws-x-xx-xxxx-x.pooler.supabase.com:6543/postgres`.
   4. Use the **pooled** connection string (port 6543, "Transaction" mode)
      for `BANKASSIST_DATABASE_URL` — Cloud Run's request-scoped
      connections suit a pooler better than a direct connection (port
      5432). Note this app uses **psycopg2** (sync SQLAlchemy), not
      asyncpg — psycopg2 doesn't do the automatic server-side prepared-
      statement caching that breaks under pgBouncer transaction mode, so
      the `statement_cache_size=0` fix documented in olink-dispatch's
      CLAUDE.md (an asyncpg-specific gotcha) does not apply here and no
      matching code exists or is needed. If you ever do see prepared-
      statement/pooling errors in production logs, the standard fallback
      is switching to the direct connection string (port 5432).
   5. This new project is **only** for bank-assist. Don't add
      `olink-dispatch`'s tables to it, and don't add bank-assist's tables
      to `olink-dispatch`'s project — two separate Supabase projects
      under one Olink organization, same as this is a separate GitHub repo
      under one Olink account.

## One-time GCP setup

```bash
export PROJECT_ID="your-project-id"
export REGION="us-east1"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com

# Artifact Registry repo to hold the container images
gcloud artifacts repositories create bankassist \
  --repository-format=docker --location="$REGION" \
  --description="Olink Bank Assist images"

# A deploy-only service account — NOT project owner/editor. Scoped to
# exactly what the GitHub Actions workflow needs: push images, deploy
# Cloud Run, and read the two secrets below.
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
# ^ Treat this file as a secret. Add its contents to the GitHub repo secret
#   GCP_SA_KEY below, then delete the local copy — don't commit it, don't
#   leave it lying around. (Workload Identity Federation avoids this
#   long-lived key entirely; worth moving to once this matters more than
#   an MVP demo does.)

# Secrets Cloud Run reads at startup — never baked into the image or the
# workflow file.
echo -n "postgresql://...(your new bank-assist Supabase project's pooled connection string, port 6543)..." | \
  gcloud secrets create bankassist-database-url --data-file=-
echo -n "your-gemini-api-key" | \
  gcloud secrets create bankassist-gemini-api-key --data-file=-
# (Gemini is optional — omit that secret and drop the GEMINI_API_KEY line
#  from deploy.yml's --set-secrets if you want to launch in extractive mode
#  first and add conversational answers later.)
```

## First deploy (manual, to get the live URL)

Do this once so the service exists and you have its URL — after this,
`deploy.yml` takes over on every push to `main`.

```bash
cd /path/to/olink-bank-assist   # your local clone
gcloud auth configure-docker "${REGION}-docker.pkg.dev"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/bankassist/bankassist"
docker build -t "$IMAGE:initial" .
docker push "$IMAGE:initial"

gcloud run deploy bankassist \
  --image "$IMAGE:initial" --region "$REGION" --port 8000 \
  --allow-unauthenticated --min-instances 0 --max-instances 3 --memory 512Mi \
  --set-secrets "BANKASSIST_DATABASE_URL=bankassist-database-url:latest,GEMINI_API_KEY=bankassist-gemini-api-key:latest"

# Note the URL gcloud prints (https://bankassist-xxxxx-xx.a.run.app), then:
gcloud run services update bankassist --region "$REGION" \
  --set-env-vars "APP_BASE_URL=https://bankassist-xxxxx-xx.a.run.app"
# ^ needed for Telegram webhook registration to construct the right URL later
```

Seed the tenants against the live database once (run locally, pointed at
the same `BANKASSIST_DATABASE_URL` you put in Secret Manager):

```bash
export BANKASSIST_DATABASE_URL="postgresql://..."  # your new Supabase project's pooled URL
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m bankassist.seed         # fictional Demo Bank
.venv/bin/python -m bankassist.seed_cbe
.venv/bin/python -m bankassist.seed_dashen
.venv/bin/python -m bankassist.seed_awash
```

## Wire up auto-deploy

In the GitHub repo → Settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `GCP_SA_KEY` | full contents of `bankassist-deployer-key.json` |
| `GCP_PROJECT_ID` | your project ID |
| `CLOUD_RUN_HOSTNAME` | the host from the URL above, e.g. `bankassist-xxxxx-xx.a.run.app` |

From then on, every push to `main` that passes CI redeploys automatically.
Trigger a one-off redeploy anytime via Actions → Deploy to Cloud Run →
Run workflow.

## Verify

```bash
curl https://<your-cloud-run-url>/health
# {"status":"ok","llm":"gemini"|"extractive-fallback"}
```

Then open `/widget?bank=cbe` and `/admin` at that URL — this is the link
you hand a prospect instead of demoing off a laptop.
