# Split the Cloud Run runtime identity from the CI deployer

Roadmap item, not yet run. `bankassist-deployer` is currently **both** the
CI identity that pushes images and runs migrations, and the identity Cloud
Run runs the container as (`deploy.yml`'s `--service-account` flag) — more
privilege than the running service needs: the container only ever calls
`secretmanager.secretAccessor` to read `BANKASSIST_DATABASE_URL` and the two
LiveKit secrets, never Artifact Registry, never IAM, never anything else
`bankassist-deployer` can do.

**Why this is a runbook and not a diff.** Flipping `deploy.yml`'s
`--service-account` to a name that doesn't exist yet breaks the *next* auto
deploy on every push to `main` — this pipeline deploys automatically on a
green CI run, with no manual gate. `gcloud` is unreachable from this sandbox
(no credential, and it isn't installed), so nothing here could be verified
before landing. Run the setup for real first; only then does changing the
workflow become safe.

## One-time setup

```bash
PROJECT_ID="<the bankassist GCP project>"

gcloud iam service-accounts create bankassist-runtime \
  --project "$PROJECT_ID" \
  --display-name="Bank Assist Cloud Run runtime"

# Exactly the one role the container calls at startup — nothing else.
for SECRET in bankassist-database-url bankassist-livekit-api-key bankassist-livekit-api-secret; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --project "$PROJECT_ID" \
    --member="serviceAccount:bankassist-runtime@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

## Cut over

Once the service account exists and the three bindings above are confirmed
(`gcloud secrets get-iam-policy <secret>` should list `bankassist-runtime`
on each), change exactly one line in `.github/workflows/deploy.yml`:

```diff
-            --service-account "bankassist-deployer@${{ secrets.GCP_PROJECT_ID }}.iam.gserviceaccount.com" \
+            --service-account "bankassist-runtime@${{ secrets.GCP_PROJECT_ID }}.iam.gserviceaccount.com" \
```

Push, let CI go green, and watch the deploy: `bankassist-deployer` still
does the pushing and migrating (it needs Artifact Registry write and DB
access to do that), but the **revision** that actually serves traffic runs
as `bankassist-runtime`. Confirm with:

```bash
curl -s "$(gcloud run services describe bankassist --project "$PROJECT_ID" --region us-east1 --format='value(status.url)')/health"
```

A `200` with `llm: vertex` and `llm_ready: true` means the new identity can
still reach the database and Vertex — if either secret access was missed
above, the revision fails to start with the exact "Permission denied on
secret" error this same split caused once already when `bankassist-deployer`
was first wired up without it (see CLAUDE.md's Cloud Run gotchas).

`bankassist-deployer` keeps `secretmanager.secretAccessor` too after this —
CI needs it to check `DB_URL` is set before running migrations — this split
only narrows the **runtime** identity, not the CI one.
