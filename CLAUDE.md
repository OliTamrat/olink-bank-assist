# Olink Bank Assist — Claude Code Context

## CRITICAL: Git Commit Rules (GOLDEN RULE)

- **Every commit is authored AND committed by Oli Tamrat
  (`Oli Tamrat <olitamrat@gmail.com>`) — required for IP registration.**
- **NEVER include Claude attribution, `Co-Authored-By` lines, session
  trailers, or any AI author/co-author reference in commit messages or git
  metadata.** Commit messages read as if written solely by the developer.
- Before committing, ensure `git config user.name "Oli Tamrat"` and
  `git config user.email "olitamrat@gmail.com"` are set in this repo.

**Read `README.md` for the service itself.** This file is product strategy,
the phased roadmap, and the rules that must not regress.

## What this project is

**Olink Bank Assist** — a white-label AI banking assistant for Ethiopian banks
and microfinance institutions, by Olink Technologies. Each bank deploys a
branded assistant its customers talk to about accounts, transfers, loans,
fees, saving, and financial education — in **Amharic, Afaan Oromo, Tigrinya,
Somali, or English** — over a web chat widget and Telegram (Ethiopia's
dominant messaging channel). Phase 3 adds authenticated account servicing.

**This repo is the product's only home.** It briefly incubated inside
`olink-dispatch` (`bank-assist/` on branch `claude/ethiopian-banking-chatbots-pkdp1c`,
PR #12, closed unmerged) — founder decision 2026-08-04: products never share
repos. Do not add Bank Assist code to any other repo.

## Why this wins in Ethiopia (the strategic moat)

1. **Data residency is law.** Personal Data Protection Proclamation
   No. 1321/2024, Art. 22: personal data collected in Ethiopia must be stored
   on servers located in Ethiopia. Foreign SaaS chatbot vendors can't easily
   comply. Olink already has the Ethio Telecom ECS deployment path and
   pricing worked out (see Onekof Tier 1) and INSA-certification experience
   (Onekof P1–P6, certified 2026-07-03). Lead every bank pitch with this.
2. **Telegram-first.** Ethiopian banks already run Telegram presences; a bot
   means zero install friction on cheap Android phones.
3. **Native-language support gap.** Tens of millions of new digital banking
   users (telebirr 50M+); support is English-first while customers think in
   Amharic/Afaan Oromo. The 5-language i18n capability is proven in Olink
   School Bus.
4. **Agent discipline is proven.** The safety doctrine below is the
   olink-dispatch agent playbook (tool-output-is-truth, intent allowlists,
   approval queues, audit logs) applied to banking.

## Stack

- **API:** FastAPI, Python 3.12, SQLAlchemy 2.x; SQLite dev / Postgres prod
- **LLM:** Gemini via REST (httpx, no SDK), `gemini-2.5-flash` default, with a
  deterministic extractive fallback — the demo works with **no API key**
- **Retrieval:** dependency-free BM25 (Ge'ez-script aware), per-tenant
- **Channels:** embeddable widget (`static/widget.html`), Telegram webhook
- **Admin:** single-page panel (`static/admin.html`) — KB CRUD, transcripts,
  handoff queue

## Safety doctrine (NEVER regress)

1. **Tool output is truth.** Answers come from the bank's knowledge base.
   LLM mode prompts context-only; no-key mode quotes retrieved chunks
   verbatim. The bot must never invent a rate, fee, or requirement — one
   hallucinated interest rate screenshot kills a bank deal.
2. **Allowlist, not blocklist.** Only greeting / product-question /
   investment-education intents are answered autonomously
   (`AUTO_ANSWER_INTENTS` in `classifier.py`). The intent rules are
   deterministic regexes — the safety floor never depends on a model.
3. **Account-specific → fixed security template.** The bot has no account
   access in Phases 1–2 and must never claim otherwise.
4. **Education, never advice.** Investment answers always append the
   education-not-advice disclaimer in the user's language. No personalized
   recommendations — investment advisory is an ECMA-licensed activity.
5. **Unknown → handoff, not guessing.** Empty retrieval files a `Handoff`
   row; every knowledge gap becomes visible content work for the bank.
6. **Multi-tenant from day one.** Every query filters `bank_id`; tests assert
   cross-tenant isolation (documents, chats, conversations, admin tokens).
   Don't break them.
7. **Secrets fail closed, compare constant-time** (`hmac.compare_digest` for
   admin tokens and Telegram webhook secrets — same doctrine as the dispatch
   cron secret).
8. **Audit log** (`actor/action/entity_type/entity_id/metadata`) on handoffs
   and every admin mutation. `entity_id` is TEXT — always `str(uuid)`.

## Current phase

**Phase 1 MVP complete (2026-08-04); infrastructure hardened same day.**
35 tests green, mypy `--strict` clean, ruff clean. Smoke-tested end to end in
EN + AM (retrieval answers, advice disclaimer, account refusal,
unknown→handoff, Telegram webhook with mocked send). Seeded fictional
**Demo Bank Ethiopia** (13 docs, EN+AM, illustrative figures — deliberately
not branded as any real institution).

Infrastructure in place (founder direction 2026-08-04: "build the foundation
right"):
- **CI** (`.github/workflows/ci.yml`): ruff + mypy strict + pytest + golden
  evals + Alembic up/down/up round-trip, on Python 3.11 and 3.12, plus a
  Docker build that boots the container and curls `/health`.
- **Alembic migrations** — baseline `0001`. Deployed environments migrate;
  `init_db()` create_all is tests/dev only. URL comes from
  `BANKASSIST_DATABASE_URL` only (env.py reads settings; alembic.ini has none).
- **Golden-question eval gate** — `python -m bankassist.evals`, 14 cases
  (products, how-tos, Amharic, all guardrails). Run in target config before
  any model/prompt/KB change ships.
- **Structured JSON logging** — `request` + `chat_handled` events, metadata
  only. **Chat text is never logged** (it's personal data).
- **Rate limiting** on `/chat` — per-IP and per-conversation sliding windows,
  env-tunable, per-process (Redis behind the same `allow()` when
  multi-instance).
- **Dockerfile** — non-root, binds `$PORT` (default 8000; match `--port` on
  deploy). Static files live inside the package so the installed wheel serves
  them.

**CBE sales-demo tenant (2026-08-05, hardened same day).**
`bankassist/seed_cbe.py` seeds a second tenant (`slug=cbe`) from Commercial
Bank of Ethiopia's real public information — 19 documents (17 EN, 2 AM),
CBE's maroon brand color, and a mandatory `Bank.disclaimer` banner
("Unofficial prototype... Not affiliated with, endorsed by, or an official
channel of CBE") rendered in the widget so it can never be mistaken for
CBE's own product. Every figure is sourced — `SOURCES.md` documents each one
with a citation and pull date, and is explicit about which figures were
contested across sources and therefore described qualitatively rather than
guessed (exact fixed-deposit rates, telebirr transfer fee tiers, ATM fee
percentages, precise branch hours). `combanketh.et` itself returns 403 to
automated fetches — content is drawn from secondary sources that corroborate
CBE's public material. Coverage: savings, fixed deposits, diaspora accounts,
CBE Noor (interest-free/Sharia banking), business/current accounts, mobile
banking + CBE Birr activation, telebirr/interbank/international transfers
(incl. the real SWIFT code CBETETAA), ATM cards, agent banking, loans,
fraud-prevention safety tips, branches/contact, and financial education.
**Deliberately excluded:** CBE's real fraud-loss figures and 2024 ATM
glitch incident — real, reported news, but not appropriate for a sales-demo
assistant to surface about the prospect it's pitching to.

**Adversarially stress-tested (founder direction: "don't be conservative,
test against all odds they might ask") — three real bugs found and fixed,
not cosmetic:**

1. **Retrieval had no confidence floor.** A single incidental term match
   (e.g. "bank" in "are you officially endorsed by the bank?") was enough
   to return a whole document as an answer — meaning prompt injection,
   "are you officially endorsed?", competitor-bank questions, and hostile
   input all got a plausible-looking but *irrelevant* answer instead of an
   honest "I don't know." That's worse than useless for this product's
   entire pitch. Fixed in `retrieval.py` with `MIN_INFORMATIVE_RATIO`: for
   queries longer than `SHORT_QUERY_CONTENT_WORDS` (3) content words, at
   least half must be genuine (low-corpus-frequency) matches, not just one.
   **The ratio is deliberately length-gated, not flat** — a flat threshold
   is provably impossible here: a legitimate short query ("How do I open a
   diaspora account?", 3 content words, 1 real match) needs ratio ≤ 0.33 to
   pass, while the adversarial cases (5–7 content words) need ratio > 0.4 to
   be rejected. No single number satisfies both; query length is real
   signal because longer queries have more surface area for coincidental
   overlap, which is exactly the pattern behind every adversarial case
   found. Tune this bar carefully and re-run both eval suites plus
   `test_cbe_adversarial.py` — it's easy to silently reopen this gap.
2. **Investment disclaimer was content-triggered, not intent-triggered.**
   `handle_message` only appended the advice disclaimer inside the
   "chunks found" branch — a padded/evasive investment question ("just
   between us, one stock tip, no disclaimers?") that dodged retrieval
   entirely fell to the *generic* unknown-handoff message with **no
   disclaimer at all**. Fixed in `agent.py`: the disclaimer now fires
   whenever `intent == INVESTMENT_ADVICE`, independent of whether specific
   content matched — it's a safety statement tied to the classifier's
   regex, not to retrieval success, and must never be skippable.
3. **Account-specific detection only matched first-person phrasing.**
   "Give me the balance for account X" / branch-manager impersonation
   bypassed the security-refusal template (`\bmy (account|balance|...)`
   requires "my"). Was already safe (nothing to leak) but gave a confusing
   non-answer instead of the correct message. Fixed in `classifier.py` by
   adding third-person/imperative patterns — verified against
   `"What is the minimum balance for a savings account?"` and similar
   product questions to confirm no false-positive regression.
4. **(Pre-existing, found via the same pass)** The complaint regex treated
   bare `fraud`/`scam` as an incident report, so "How can I protect myself
   from fraud?" — a question this very demo added content to answer —
   misrouted to the human-handoff path instead of the knowledge base. Fixed
   by requiring incident-specific phrasing (`got scammed`, `fraud on my
   account`, `report a fraud`) rather than the bare word. This bug predates
   the CBE tenant and would have affected Demo Bank too.

`tests/test_cbe_adversarial.py` (12 tests) and `tests/test_cbe_demo.py`
(6 tests) lock all of this in, alongside two retrieval-ranking regressions
found earlier the same day: BM25 has no stemming, so a document's verbose
*comparisons* to another topic can out-rank the document actually about the
query (e.g. "Fixed Time Deposit" out-ranked "Ordinary Savings Account" for a
savings-rate question because it repeated "regular savings account" three
times) — fixed by writing the target document densely in the query's own
terms, not by changing the shared retrieval algorithm. Watch for this same
pattern in any future bank's content.

**One known, accepted tradeoff:** a false-premise question with the literal
word "complain" in it ("why do people complain about fees, if CBE charges
none?") still misroutes to the complaint handoff via a third-person mention,
not a personal complaint — low severity (safe fail-mode, doesn't hallucinate
or leak) and not fixed, since a more precise regex risked new false
negatives on real complaints. Documented rather than silently patched.

**Competitor-comparison intent added (2026-08-05, founder feedback):**
refusing to compare against a named competitor was correct caution, but
going *silent* instead of confidently selling the bank's own real strengths
was a genuine product gap, not a safety win — a bank chatbot that can't say
anything when asked "is X better than you?" looks broken, not careful. New
`COMPARISON` intent in `classifier.py`, detected via `_comparison_re()`,
answered as a fixed, deterministic template — **never via the fuzzy BM25
retriever**, and **never by naming or making a claim about the specific
competitor**, only ever the bank's own sourced facts, positively framed.
Two design points worth preserving if this is touched again:
- **The classifier hardcodes no bank's name.** It's shared across every
  tenant; `classify_intent(text, bank_aliases=...)` takes the calling
  tenant's slug/name as call-time arguments (`agent.py`'s `_bank_aliases()`
  builds them from the `Bank` row), so "is Dashen better than CBE" is
  caught for the `cbe` tenant without the module knowing "CBE" exists.
  Name-agnostic phrasings ("better than you", "which bank is better")
  always work with zero aliases.
- **Content lookup is a direct category query, not retrieval.** A document
  tagged `agent.WHY_CHOOSE_CATEGORY` ("why-choose-us") is looked up by
  `bank_id` + `category` directly — deliberately bypassing the BM25
  informative-match gate entirely. A comparison question structurally
  contains a competitor's name, which by design never appears in this
  bank's own content, so the fuzzy scorer would have to be *reopened* to
  ever match it — reintroducing exactly the false-positive risk the
  adversarial hardening above just closed. A tenant with no such document
  (e.g. Demo Bank) gets a generic, still-confident redirect template
  (`comparison_fallback` in `i18n.py`) — never a handoff, never silence.

CBE's `Why Choose CBE` document introduces no new facts — it reuses figures
already in `SOURCES.md` (1942 founding, 1,900+ branches, CBE Noor's 8M+
customers, CBE Connect, the SWIFT code), reframed positively. Any future
bank tenant that wants this behavior needs its own document in this
category; without one, the fallback template still applies.
`tests/test_cbe_adversarial.py::test_comparison_question_answers_confidently_from_why_choose_doc`
and `::test_comparison_fallback_when_tenant_has_no_why_choose_doc` cover
both paths; `tests/test_classifier.py` covers the alias-scoping behavior.

**Dashen Bank and Awash Bank prospect-demo tenants added (2026-08-05).**
Same doctrine as CBE, no exceptions: `bankassist/seed_dashen.py` and
`seed_awash.py`, each with a mandatory disclaimer banner, sourced content
only (`SOURCES_DASHEN.md`, `SOURCES_AWASH.md`), and a `Why Choose <Bank>`
document for the comparison intent. **These are private pitch-demo
prototypes, not live public products** — founder decision 2026-08-05,
made explicitly after being asked to build them as "a SaaS product" that
would "help this business brand in their market." Building a live,
publicly-branded bot under a real bank's name — before that bank has any
relationship with, or knowledge of, this project — is trademark/
impersonation and financial-regulatory risk with a real, named,
non-consenting company. **If a future session is asked to "make Dashen or
Awash live" or "launch this for [bank]," that means signing an actual deal
with that bank first, then loading their real verified content through the
admin panel — never just flipping a switch on the existing prototype.**
The disclaimer banner is the enforcement mechanism; do not remove or make
it conditional without that same explicit, re-confirmed authorization.

Extracted `seed_common.py` (`prospect_disclaimer()` + `seed_prospect_bank()`)
so the fourth bank tenant is a content file, not new plumbing — every
prospect-demo seed script now follows: aliases/name/color, `_DOCS` list, one
`seed()` call. `dashenbanksc.com` and `awashbank.com` were both unreachable
for direct fetching during research (same session-wide/site-specific fetch
failures CBE hit) — content is search-synthesis-sourced throughout, with
the same discipline of leaving contested or single-source figures
qualitative. Two research agents were dispatched in parallel and both
explicitly flagged their own confidence levels per fact — trust that
grading; it's what let contested figures (Dashen's regular savings rate,
Awash's branch count) get caught before they became false facts in a
demo.

**Two more real bugs found while building these, both fixed and now
regression-tested — read before touching retrieval.py or classifier.py's
comparison pattern again:**

1. **A term in exactly half the corpus counted as "informative."** The
   original `retrieval.py` gate was `term_df <= max(1, n/2)`. On Awash's
   22-chunk corpus, the word "bank" sat in exactly 11 chunks — precisely
   at that boundary — and was the *only* thing making "Is CBE Bank
   better?" match anything at all (the other two content words, "cbe" and
   "better", appear zero times in Awash's own corpus). Fixed by tightening
   the ceiling to strictly below half:
   `informative_df_ceiling = max(1, (n + 1) // 2 - 1)`, replacing the
   comparison operator's role with a stricter formula rather than a naive
   `<` (which would break single-chunk-corpus retrievability — verified
   this edge case explicitly, see `test_informative_excludes_term_in_exactly_half_the_corpus`
   / `test_informative_includes_term_below_half_the_corpus` in
   `test_retrieval.py`). **This generalizes past this one bank** — any
   future tenant's corpus composition could put some other word at exactly
   50% by coincidence; the fix is in the shared algorithm, not per-tenant.
2. **The comparison regex required an explicit "than X."** "Is CBE
   better?" (bare, no "than [bank]") didn't match `classify_intent`'s
   alias-specific pattern, so asking a bank's own assistant "is CBE
   better?" about *itself* fell through to ordinary retrieval instead of
   the comparison template. Fixed by adding a bare `\bis {alias}
   (better|worse)\b` alternative (still also matches the "than X" form,
   since that's a superset) in `_comparison_re()`. **Deliberately not
   extended to the "is [other named bank] better?" direction without an
   explicit "than {this bank}"** — see the existing scoping comment in
   `classifier.py`; that stays a documented limitation
   (`test_dashen_demo.py`'s cross-tenant test and
   `test_awash_demo.py::test_comparison_question_does_not_leak_unrelated_document`
   assert the *safe* fallback for it: no wrong-document leak, not full
   comparison-intent coverage).

## Roadmap over the horizon

### Phase 1 — Demo bot ✅ (this repo, done; infra hardened)
Remaining polish, not blockers:
- [ ] Set `GEMINI_API_KEY` and eyeball answer quality in all 5 languages,
      then run `python -m bankassist.evals` in that mode
- [ ] Linguist review of OM/TI/SO strings in `i18n.py` — **founder decision
      2026-08-04: parked, explicitly NOT a blocker.** Revisit before a real
      bank pilot (Onekof TSV workflow).
- [x] Load a real bank's *public* website content → done 2026-08-05, now
      three tenants (CBE, Dashen, Awash) — see above and `seed_common.py`.
      Loaded via seed scripts rather than the admin panel UI at the time.
- [x] Admin panel bulk-import → done 2026-08-05.
      `POST /admin/api/{slug}/documents/bulk` accepts `{"documents": [...]}`
      (same shape as the single-document `DocumentIn`, up to 200 per
      request), reindexes every document, and is **all-or-nothing**: any
      unsupported `language` code in the batch rejects the whole request
      with 422 (`invalid_documents` lists which entries) rather than
      importing half a knowledge base and leaving gaps for the admin to
      notice later. `admin.html`'s Knowledge Base tab has a matching Bulk
      Import card — paste a JSON array or pick a `.json` file (read
      client-side via `FileReader`, no upload endpoint needed). This is the
      real onboarding path for **Phase 2's "their real knowledge base"** —
      a bank/MFI's content team exports or is handed a JSON list, not a
      one-off Python seed script written per-tenant the way CBE/Dashen/Awash
      were.
- [x] Deploy demo instance → GCP + Supabase one-time setup done 2026-08-06/07
      (founder-executed, per `DEPLOY.md`): dedicated project
      `olink-bank-assist`, billing linked, APIs enabled, Artifact Registry
      repo, `bankassist-deployer` service account with its four scoped
      roles, `bankassist-database-url` secret pointed at a new, separate
      Supabase project (never `olink-dispatch`'s project, never
      shared/linked) using the pooled connection string (port 6543,
      "Transaction" mode).
      **`deploy.yml` hardened 2026-08-07 to close two real automation
      gaps found while wiring this up, not just documentation:** (1) it
      referenced a `bankassist-gemini-api-key` secret that was never
      created (Gemini is optional — extractive mode needs no key) — the
      deploy would have failed outright on `--set-secrets` referencing a
      nonexistent secret; removed. (2) **nothing anywhere ran Alembic
      migrations or the tenant seed scripts against the live database** —
      the Dockerfile's `CMD` only launches uvicorn, and `DEPLOY.md` had
      left both as manual local steps. Folded into `deploy.yml` itself: a
      step pulls `BANKASSIST_DATABASE_URL` from Secret Manager (via the
      deployer SA's existing `secretmanager.secretAccessor` role) and runs
      `alembic upgrade head` + all four `seed*.py` scripts before every
      deploy — safe to run unconditionally since Alembic no-ops on an
      up-to-date schema and every seed script skips banks that already
      exist. Also dropped the `CLOUD_RUN_HOSTNAME` GitHub secret
      requirement entirely — a step now self-discovers the live Cloud Run
      URL via `gcloud run services describe` right after deploy and sets
      `APP_BASE_URL` itself, so it stays correct even if the service is
      ever recreated. **Remaining required GitHub Actions secrets: just
      `GCP_SA_KEY` and `GCP_PROJECT_ID`** — everything else in the deploy
      path is now fully automated end to end on every push to `main` that
      passes CI.
      **Found earlier while wiring this up: `pyproject.toml` had no
      Postgres driver at all** — `sqlalchemy` alone doesn't ship one, so
      setting `BANKASSIST_DATABASE_URL` to any `postgresql://` URL would
      have failed immediately with `ModuleNotFoundError` at
      `create_engine()` time. Added `psycopg2-binary` (verified:
      `create_engine()` now resolves the `psycopg2` driver for the plain
      `postgresql://` scheme, no URL changes needed anywhere). Also: this
      app is **sync SQLAlchemy with psycopg2**, not asyncpg — do not
      import the asyncpg-specific `statement_cache_size=0` /
      pgBouncer-prepared-statement fix from olink-dispatch's CLAUDE.md
      into this repo; it's for a different driver with a different
      (protocol-level) prepared-statement caching behavior that psycopg2
      doesn't have. If pooling issues ever do show up in production logs,
      the standard fallback is the direct (port 5432, non-pooled)
      connection string, not that fix.
      **LIVE as of 2026-08-07** — `https://bankassist-430565798339.us-east1.run.app`,
      revision `bankassist-00003-5jp` serving 100% of traffic, all four tenants
      (demo, cbe, dashen, awash) seeded in the production Supabase database.
      Four more real bugs surfaced only by running the pipeline against
      production, each fixed in its own PR:
      (a) **a failing secret fetch didn't stop the job** — bash's `set -e`
      does not propagate a failing command substitution through a plain
      assignment, so a missing secret silently left `BANKASSIST_DATABASE_URL`
      empty and failed much later with a confusing SQLAlchemy URL-parse
      error; now `|| exit 1` on the substitution itself.
      (b) **a trailing newline in the secret** (from piping a PowerShell
      string into `gcloud secrets create --data-file=-`) produced
      `FATAL: database "postgres\n" does not exist`.
      (c) **a UTF-8 BOM in the secret** — Windows PowerShell 5.1's
      `Out-File -Encoding utf8` silently prepends `EF BB BF`, which is not
      whitespace, survives a plain trim, and makes SQLAlchemy raise the same
      generic "Could not parse SQLAlchemy URL" error as an *empty* string
      does. The deploy now strips both, so a re-broken secret cannot silently
      take the deploy down again.
      (d) **the Cloud Run revision's runtime service account** is a different
      identity from the CI deployer SA. Without `--service-account`, Cloud Run
      defaulted the revision to the project's generic Compute Engine default
      SA, which had no `secretAccessor` — so migrations succeeded (they run in
      CI, as the deployer) while the revision itself failed to start. The
      deploy now pins `bankassist-deployer` as the runtime identity too.
      **Known tradeoff:** that SA is now both CI deployer and runtime
      identity, more privilege than the running service needs — worth
      splitting into a dedicated minimal runtime SA.
- [ ] **Add `GEMINI_API_KEY` — the highest-leverage change left.** Without it
      the assistant runs extractive-only: `_extractive_answer()` pastes the
      top retrieved chunk back verbatim rather than composing an answer, so
      replies are topically right but do not address the specific question
      asked. That symptom reads as "needs more data" or "needs training" and
      is neither — more documents make the pasted text longer, not more
      responsive. `generate_answer()` is already written and already
      constrained (answer only from context, never invent a figure); it needs
      the key in Secret Manager and a line back in `--set-secrets`.
- [ ] Connect a BotFather bot via `POST /admin/api/{slug}/telegram/connect`
      (needs public HTTPS)

### Phase 2 — First pilot (one bank or MFI)
Target: a bank innovation department, or a microfinance institution / digital
lender (smaller, faster procurement, hungrier).
- Their real knowledge base, their brand color/logo on the widget
- **Analytics dashboard**: deflection rate, top questions, language mix —
  "top questions" is product intelligence banks don't have; it sells renewals
- Embedding retrieval behind the same `retrieve()` interface (BM25 stays as
  fallback); LLM intent refinement **above** the rules floor, never replacing it
- Human-agent console for the handoff queue (or webhook into the bank's
  existing contact-center tool)
- **Move hosting in-country (Ethio Telecom ECS) before real customer chat
  logs exist** — chat content is personal data under Art. 22 even without
  account linkage. Reuse Onekof's `deploy-et.sh` pattern and ECS sizing.
- Contract must include: golden-question eval suite run before every KB/model
  change; the education-vs-advice line in writing.

### Phase 3 — Authenticated account servicing
- OTP-based session auth; **read-only first** (balance, mini-statement),
  then card block. Core banking integration goes through the bank's
  middleware/ESB team (most Ethiopian banks run T24/Flexcube).
- INSA certification for this product (Onekof playbook)
- Per-action audit with customer identity; retention policy decided with the
  bank, never "forever"
- NBE consumer-protection directives review before launch

### Phase 4 — Scale & financial education layer
- ESX / capital-markets explainers, savings nudges; possible co-brand with
  ECMA's investor-education mandate (a partnership angle beyond single banks)
- Additional channels: WhatsApp Business, USSD/IVR for feature phones
- Multi-bank operations: shared model improvements, per-tenant KBs strictly
  isolated
- Business model: setup fee + monthly SaaS tiered by conversation volume
  (banks are used to enterprise pricing; don't price per-seat)

## Reuse map (use resources, never code-mix repos)

| Need | Source | What to copy (patterns, not imports) |
|---|---|---|
| Agent guardrails, approval queues, audit log | `olink-dispatch` | Doctrine already ported into this repo |
| 5-language i18n + linguist TSV review | `Olink-School-Bus`, `onekof-platform` | Review workflow for `i18n.py` |
| Ethiopia deployment, INSA, Art. 22 residency | `onekof-platform` | `deploy-et.sh`, ECS pricing brief, counsel brief format |
| Cloud Run + Secret Manager + cron patterns | `olink-dispatch` | Deploy flags, fail-closed cron secret |
| Stripe/subscription machinery (Phase 4) | `olink-dispatch` | httpx-REST webhook idempotency (`stripe_events` claim-first) |

## Workflow rules

1. Plan before code for non-trivial changes; surface tradeoffs explicitly.
2. Tests before merge — guardrail behavior and tenancy isolation must stay
   covered; new intents need classifier tests.
3. Never commit `.env` or real bank content; the seeded bank stays fictional.
4. Conventional Commits; `main` deployable; work in feature branches.
5. Demo figures are always labeled "illustrative" — never present them as a
   real institution's terms.

## Gotchas

- **Extractive mode is a feature, not a bug** — the assistant must stay fully
  demoable with no LLM key; never make the model a hard dependency.
- The retrieval "informative match" gate (stopwords + df ≤ max(1, n/2) in
  `retrieval.py`) is what makes the bot say "I don't know" instead of
  answering chess questions with mobile-banking excerpts. Tune with care and
  keep `test_unknown_question_creates_handoff_instead_of_guessing` green.
- Language detection: Ethiopic script defaults to Amharic with a Tigrinya
  orthographic tell (the ኣ series). Users can pin a language; an explicit
  `language` in the chat payload pins the conversation.
- FastAPI dependency caching means `require_admin` and route handlers share
  one DB session per request — safe to mutate the `Bank` from either.
- `pkill -f <pattern>` matches its own shell in sandbox environments — use a
  character-class pattern like `"uvicorn bankassi[s]t"` (exit 144 otherwise).
- Telegram `sendMessage` failures are logged, never raised — a Telegram
  outage must not 500 the webhook (Telegram retries the whole update).
- **Schema changes need an Alembic migration** (never edit a committed one —
  dispatch rule). `init_db()`/create_all is for tests and throwaway dev DBs
  only; CI asserts `upgrade head → downgrade base → upgrade head` works.
- Static files live at `bankassist/static/` **inside the package**
  (package-data) so the Docker `pip install .` image serves them; a top-level
  `static/` dir will silently not ship.
- Rate limiters live on `app.state`, created in the lifespan — each
  TestClient context gets fresh ones, so tests can't trip each other's
  limits. Keep it that way.
- Ruff is configured with `flake8-bugbear.extend-immutable-calls` for
  `fastapi.Depends`/`fastapi.Header` — don't scatter `noqa: B008`.
- Log through `log_event()` and never include chat text or tokens in log
  fields; the JSON formatter emits whatever it's given.
