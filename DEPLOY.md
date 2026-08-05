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
2. **Which Postgres?** SQLite (the local default) does not work on Cloud
   Run — it can scale to zero and back, and can run more than one instance
   under load, so local-disk SQLite would silently lose or fork data.
   Recommended: **Supabase** (same pattern `olink-dispatch` already uses)
   or **Neon** (same pattern `gada-global-5k` already uses) — both are a
   connection string away, no VPC connector needed. Cloud SQL is the
   all-GCP alternative but needs a Serverless VPC Connector to reach from
   Cloud Run, which is meaningfully more one-time setup for a
   single-service MVP. Pick whichever you already have on hand.

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
echo -n "postgresql://...(your Supabase/Neon connection string)..." | \
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
BANKASSIST_DATABASE_URL="postgresql://..." .venv/bin/python -m alembic upgrade head
BANKASSIST_DATABASE_URL="postgresql://..." .venv/bin/python -m bankassist.seed
BANKASSIST_DATABASE_URL="postgresql://..." .venv/bin/python -m bankassist.seed_cbe
# (seed_dashen / seed_awash once those land)
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
