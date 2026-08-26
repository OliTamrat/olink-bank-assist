# What only a human with credentials can do

Everything here is blocked on access an agent sandbox does not have — a live
`gcloud` session, the production database, or a signed-in admin account. None
of it is blocked on code. Each item links to its own runbook where one exists;
this page is the ordering and the reason, so nothing sits half-remembered in a
chat log.

Ordered by value per minute of your time.

---

## 1. Create yourself an administrator account · ~5 minutes

**Why first:** nothing else on this list can be done without it. A seeded
tenant holds documents and roles and **no users**, so on 2026-08-26 every
sign-in on all four banks failed with "that email and password did not match"
— true, and it names nothing. Item 2 below needs a signed-in account with
`documents.write`; there is currently no account at all.

If you hold the production connection string:

```bash
export BANKASSIST_DATABASE_URL='postgresql://…'
python -m bankassist.create_admin dashen --email you@bank.et
```

If you do not: set a repository secret `BOOTSTRAP_ADMIN_PASSWORD`, run the
**Create first administrator** workflow from the Actions tab, then delete the
secret. Full detail, and why the password is never a workflow input:
**`docs/runbooks/create-the-first-administrator.md`**.

**Check:** sign in at `/admin`. The tenant's admin token now returns `403`
naming its replacement — that is the intended end state (ADR-0031), not a
regression.

---

## 2. Apply the corpus to the live tenants · ~5 minutes

**Why first:** the corpus work of 2026-08-14 took the four tenants from 66
measured gaps to 58, and **none of it is visible to a customer yet.**
Deploying did not apply it and re-running the seeders would not either —
`seed_prospect_bank` finds the existing tenant and returns before it touches
documents. That is deliberate, and it means new documents reach production
only through the import path.

```bash
python scripts/export_new_documents.py b52d951..HEAD
```

Writes `import-demo.json`, `import-cbe.json`, `import-dashen.json`,
`import-awash.json`. Read them — they are the words a bank's customers will
see. Then for each tenant, paste into **Knowledge Base → import** in the admin
panel, signed in as a user with `documents.write`. The admin token cannot do
this any more (ADR-0031).

**Check:** ask the live widget "the ATM took my money but gave no cash" on
`dashen`. Before the import it is a knowledge gap; after, it answers.

---

## 3. Trigger the branch-prune workflow once · ~5 minutes

**Why:** `.github/workflows/prune-merged-branches.yml` (PR #114) has never been
run, and there are roughly 160 stale remote branches behind it. Every one of
them is a squash-merged branch whose work is already on `main`, so the list is
noise that makes a real unmerged branch impossible to spot — which is exactly
the check that found PR #61 during the 2026-08-14 audit.

Actions tab → the workflow → **Run workflow**. **Dry run first**, read what it
proposes to delete, then run again with write enabled.

**Check:** `git branch -r | wc -l` falls from ~160 to a handful.

---

## 4. Split the Cloud Run runtime identity · ~15 minutes

**Why:** `bankassist-deployer` is currently both the CI identity that pushes
images and runs migrations *and* the identity the running container executes
as. The container only ever reads three secrets; it does not need Artifact
Registry, IAM, or anything else that account can do. This is the one item on
the list that reduces blast radius rather than adding capability.

Full commands: **`docs/runbooks/split-runtime-service-account.md`**.

**Order matters.** Create `bankassist-runtime` and grant it
`secretmanager.secretAccessor` *first*, confirm the bindings, and only then
change the `--service-account` line in `deploy.yml` — that pipeline
auto-deploys on every green push to `main`, so a change committed before the
account exists deploys a service that cannot read its own database URL.

**Check:** `GET /health` returns `llm_ready: true` on the revision that follows
the change. That proves the new identity resolved both the database URL and the
Vertex credentials.

---

## 5. Run "Ask OKM" for the first time · ~30 minutes

**Why:** `bankassist/seed_okm.py` (ADR-0015, PR #115) has never touched a real
database. It is Phase 3 of the knowledge work — the product answering questions
over Olink's own documentation — and it is written, tested and unrun. Needs a
checkout of `olink-knowledge` as well as production access, which is why it is
last rather than because it matters least.

Full commands: **`docs/runbooks/ask-okm-refresh.md`**.

---

## Not on this list, and more valuable than any of it

Two things block work I cannot do at all, and neither needs credentials — only
a conversation:

- **A tariff sheet and card terms from each bank.** The measured gaps that
  remain are mostly prices: what a replacement card costs, the charge for using
  another bank's ATM, daily limits. Dashen's ATM limits were only answerable
  because American Express publishes the terms of its own card. Everything else
  lives in a tariff sheet that is not on the public web. **One page per bank
  closes most of the remaining backlog**, and no amount of writing substitutes
  for it — inventing a fee in a bank demo is what the doctrine exists to stop.

- **The two USSD field questions** (ADR-0032 §10): whether a cheap handset
  renders Ge'ez, and whether the gateway sends accumulated input or one
  keystroke. Half a day with three phones, and one email to the bank's USSD
  vendor. The second answer deletes a table before it is written.
