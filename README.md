# Olink Bank Assist

A **white-label AI banking assistant for Ethiopian banks**. Each bank gets a
branded assistant its customers can talk to — in **Amharic, Afaan Oromo,
Tigrinya, Somali, or English** — about accounts, transfers, loans, fees,
saving, and general financial education, over a **web chat widget** or a
**Telegram bot**. When the assistant cannot or must not answer, the customer
is handed to a **live human teller on a call, inside the same conversation**.

Live at `https://bankassist-430565798339.us-east1.run.app`, deployed from
`main` by GitHub Actions on every CI-green push. The full product plan,
architecture doctrine and roadmap live in `CLAUDE.md`.

## The three tiers of an answer

Every customer message resolves into exactly one of these, in this order.
The order is the product.

| Tier | What answers | Cost | When |
|---|---|---|---|
| **1 — Curated** | The bank's own written answer, verbatim | zero — no retrieval, no model call | The question matches a curated FAQ exactly |
| **2 — Retrieved** | BM25 over the bank's knowledge base, optionally phrased by Gemini | one model call | Retrieval finds something informative |
| **3 — Live teller (ITM)** | A real person, on a LiveKit call, with the whole transcript | a human minute | Anything account-specific, anything unknown, anything the customer asks a person for |

Tier 3 is what makes this a banking channel rather than an FAQ bot. Tier 1 is
what keeps the Gemini bill from scaling with traffic on the questions everybody
asks.

## Safety doctrine (non-negotiable)

1. **We never move money, and we never see an account.** No scope at any
   verification level permits a transaction — `MONEY` is absent from every
   grant list in `teller.py` rather than withheld behind a flag, and a
   module-level `assert` refuses to import if it ever appears. Core banking
   access belongs to the *teller*, on the bank's own pre-approved screen. This
   product connects a customer to that person; it does not act for them.
2. **Tool output is truth.** Answers come from the bank's own knowledge base.
   With a Gemini key the model is instructed to answer only from retrieved
   context; with no key the assistant returns the retrieved content verbatim
   (extractive mode). It never free-associates a rate or a fee — an eval
   invariant fails any answer carrying a figure with no source.
3. **Allowlist, not blocklist.** Only greeting / question / account-procedure /
   investment-education intents are answered autonomously. Intent rules are
   deterministic regexes — the safety floor never depends on a model.
4. **Procedure yes, values never.** "How do I open an account" is public
   process and gets answered. "What is *my* balance" and anything about
   somebody else's account are vetoed first and absolutely, before any positive
   signal is considered (`classifier.answerable_without_core_banking`).
5. **Education, never advice.** Investment questions always carry the "general
   education, not personal investment advice" disclaimer, in the user's
   language.
6. **Unknown means handoff.** If retrieval finds nothing informative, the
   assistant says so and files a `Handoff` the bank sees, on a **department
   desk** with a priority — every knowledge gap becomes a content task.
7. **Multi-tenant from day one.** Every query filters by `bank_id`; tests
   assert cross-tenant isolation for documents, chats, conversations, retrieval
   caches, users and admin tokens.
8. **Permissions in code, roles in the database.** A route names a capability,
   never a role. A test fails if a route guards a permission the registry has
   never heard of.
9. **Audit log** on handoffs and every admin mutation. **Chat text is never
   logged** — `log_event()` carries metadata only.

## The live teller (ITM)

`docs/video-teller.md` is the design document. In short:

- **Presence is declared, not inferred.** A teller flips an On-duty toggle;
  the shell heartbeats every 30s against a 90s staleness window
  (`presence.py`). The Connect button appears to customers only when a teller
  is genuinely on duty *and* a media layer is configured. An earlier version
  inferred presence from whoever had the queue page open — which took the bank
  off the air whenever a teller looked at another screen.
- **The transcript travels.** The teller opens the session with everything the
  customer already said. Text chat keeps running alongside the call, because
  account numbers and reference codes are exactly what cannot be said over a
  bad line.
- **Verification is two legs**, and neither substitutes for the other:
  identity (the Fayda ID seen, **or** the Fayda number matched against the
  account record on the teller's own core-banking screen) *and* an account
  question only the holder could answer. The number-matched path exists
  because audio-only is the common case outside Addis.
- **The ID is shown, never stored.** The customer can turn their camera on for
  sixty seconds; the teller can freeze the frame in their own browser. Nothing
  is uploaded or persisted — the bank's system is the system of record, so
  holding a library of national identity documents would be pure liability.
- Ending the call propagates to both sides. The customer sees the teller's
  first name; the teller sees the customer's.

## Escalation desks

`departments.py` routes every handoff to one of eight desks — fraud, cards,
lending, international, payments, digital, accounts, general — with an
urgent/normal priority. Rules, never a model call: it is an eight-way choice
over a small stable vocabulary on the highest-volume object in the product, it
has to be explainable to a supervisor, and it has to be testable. FRAUD matches
first, because "someone took money from my card" is a fraud matter that happens
to mention a card.

`reason` (why the assistant let go) and `department` (who answers) are separate
axes. Conflating them is the trap.

## Curated answers

`faq.py` + the Curated Answers admin page. Frequent questions are surfaced from
real traffic; the bank writes the answer once; it is served **verbatim**.

Two properties that must not be relaxed:

- **Matching is exact after normalisation** — case, spacing, edge punctuation
  (including ። and ፣), a leading greeting, NFKC. No stemming, no synonyms, and
  above all no semantic similarity: "the fee for transfers *to* CBE" and
  "*from* CBE" are neighbours in any embedding space and have different
  answers. This is the one path with no downstream gate.
- **The lookup sits after every guardrail.** Putting it first is the obvious
  optimisation and would let a bank publish an answer to "what is my balance".

## Importing a bank's published pages

`ingest.py`. Paste a URL **or the page text**, see exactly what would be
imported, tick, commit. Two steps always.

- Split on headings, not length — the heading becomes the document title, and
  that title is what topic suggestions offer someone who phrased a question
  differently.
- Boilerplate is dropped first. Navigation imported onto every page becomes the
  highest document-frequency text in the corpus, so BM25 rates it worthless and
  the informativeness gate then treats every page as mostly noise. An unfiltered
  import makes retrieval *worse*, page by page.
- A section needs one prose run of 60+ characters. A card grid is a pile of
  fragments; an article has prose.
- Marketing copy is **flagged, never filtered** — flagged sections arrive
  unticked, and the judgement stays with the bank.
- Plain text is a first-class input, not a fallback. Most Ethiopian bank sites
  render in the browser, so both the URL fetch and View Source see the same
  empty shell; Ctrl+A / Ctrl+C on the rendered page is the route that works.
- The URL fetch is **SSRF-safe by construction**: https only, no credentials,
  no IP literals at all, no localhost, redirects not followed, size and time
  caps. Known limit, stated in the docstring: a hostname that *resolves* to a
  private address still gets through.

## Retrieval

Deliberately lexical (BM25): zero dependencies, works offline, handles Ge'ez
script, and every ranking decision is explainable. `retrieve()` is the single
entry point — swapping in embeddings touches nothing else.

`index.py` builds the tokenized corpus, document frequencies and the
informative-df ceiling **once per version of the content**, keyed by a
three-part version stamp (chunk count, document count, latest `updated_at`),
LRU-bounded to 8 tenants. A query scores only chunks containing one of its
terms. At 1,964 chunks that is **118.5ms → 6.9ms**, with a differential test
asserting identical chunks, order and scores against the unindexed
implementation — a faster retriever that ranked differently would be a product
change wearing a performance change's clothes.

**The corpus is the ceiling.** Nothing about the model, the prompt or retrieval
moves the answer rate as much as content does. When the assistant is
underperforming, count the documents first.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m bankassist.seed        # prints the demo admin token
.venv/bin/python -m uvicorn bankassist.api:app --port 8100
```

- Widget: <http://localhost:8100/widget?bank=demo>
- Admin panel: <http://localhost:8100/admin> (slug `demo` + the printed token)
- API docs: <http://localhost:8100/docs>

Quality gate (CI runs exactly this):

```bash
.venv/bin/ruff check . && .venv/bin/mypy bankassist \
  && .venv/bin/pytest -q && .venv/bin/python -m bankassist.evals
```

## Golden-question evals — the pre-deploy gate

`python -m bankassist.evals` runs 20 golden questions through the full agent
pipeline (products, how-tos, Amharic, and every guardrail) and exits non-zero
on any failure. CI runs it in extractive mode on every push. Before shipping
any model, prompt, or knowledge-base change, run it in the target configuration
(`GEMINI_API_KEY=... python -m bankassist.evals`). Guardrail cases are enforced
by code and must never fail in either mode.

## Database migrations

Production schema is managed by **Alembic** — `0001_initial.py` is the
baseline, head is **0022**. `BANKASSIST_DATABASE_URL` is the single source of
truth for the URL (`migrations/env.py` reads it; `alembic.ini` has none).

```bash
alembic upgrade head        # apply
alembic downgrade base      # roll back (dev only)
```

`init_db()` (create_all) remains for tests and throwaway dev databases only —
deployed environments always migrate, and the deploy workflow runs
`alembic upgrade head` **before** the new revision takes traffic.

## Docker

```bash
docker build -t bankassist .
docker run -p 8000:8000 -e BANKASSIST_DATABASE_URL=... bankassist
```

Uvicorn binds `$PORT` (default 8000) — deploy Cloud Run/ECS with a matching
`--port` or the startup TCP probe fails. CI builds the image and smoke-tests
`/health` on every push. See `DEPLOY.md` for the Cloud Run pipeline.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `BANKASSIST_DATABASE_URL` | `sqlite:///bankassist.db` | SQLAlchemy URL (Postgres in prod) |
| `GEMINI_API_KEY` | unset | Enables LLM answers; unset = extractive fallback |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Generation model |
| `GOOGLE_GENAI_USE_VERTEXAI` | unset | Use Vertex AI instead of the API-key path |
| `GOOGLE_CLOUD_PROJECT` / `VERTEX_LOCATION` | unset | Vertex project and region |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | unset | Live teller media. Unset = no Connect button, cleanly |
| `APP_BASE_URL` | `http://localhost:8100` | Public URL, used for Telegram webhooks |
| `BANKASSIST_LOG_LEVEL` | `INFO` | JSON log level |
| `BANKASSIST_CHAT_RATE_PER_IP` | `60` | Chat messages/min per client IP (`<=0` disables) |
| `BANKASSIST_CHAT_RATE_PER_CONVERSATION` | `20` | Chat messages/min per conversation (`<=0` disables) |
| `BANKASSIST_ADMIN_AUTH_FAILURES_PER_IP` | — | Admin login throttle |
| `BANKASSIST_REQUEST_TIMEOUT` | — | Outbound HTTP timeout |
| `BANKASSIST_GIT_SHA` | unset | Reported by `/health` for deploy verification |

Logs are **structured JSON** (one object per line — Cloud Logging friendly).
The `/chat` endpoint is rate-limited per IP and per conversation (in-memory
sliding window; swap for Redis when multi-instance).

The assistant is **fully demoable with no API key** — extractive mode quotes
the knowledge base directly. Add a Gemini key and answers become conversational
without changing the safety properties.

## Who can do what

Roles are per-bank database rows; permissions are code constants
(`permissions.py`). The twelve capabilities are deliberately fine-grained —
`analytics.read` is separate from `conversations.read` so a manager can see the
numbers without reading what customers typed, `audit.read` is outside the
read-everything bundle so a compliance officer can be given it alone, and
`teller.serve` is **not** part of the operator role: working a queue
asynchronously and appearing live as the bank are different jobs with different
training. `docs/per-person-logins.md` covers the login model.

## Connecting a Telegram bot

1. Create a bot with @BotFather, copy the token.
2. `POST /admin/api/{slug}/telegram/connect` with `{"bot_token": "..."}` and
   the `X-Admin-Token` header. This stores the token, mints a per-bank webhook
   secret, and registers `{APP_BASE_URL}/webhooks/telegram/{slug}`.
3. Incoming updates are verified against the secret
   (`X-Telegram-Bot-Api-Secret-Token`, constant-time compare) — fail-closed.

## Architecture

```
olink-bank-assist/
  bankassist/
    api.py            FastAPI app: chat, widget/admin pages, Telegram webhook, admin + teller API
    agent.py          Orchestration: classify -> guardrails -> curated -> retrieve -> answer
    classifier.py     Language detection, rules-based intent, the account-procedure split
    retrieval.py      Dependency-free BM25 over per-bank knowledge chunks
    index.py          Per-tenant inverted index, version-stamped, LRU-bounded
    faq.py            Curated answers: normalisation and exact matching
    ingest.py         Import published pages: fetch guard, sectioning, filters, diagnosis
    departments.py    Eight escalation desks + priority, by rule
    teller.py         Live-session scopes. No scope moves money, at any level
    presence.py       Declared on-duty state, heartbeat and staleness window
    verification.py   Two-leg identity/account verification for a live session
    livekit.py        Hand-rolled HS256 room tokens (canPublishData off)
    permissions.py    The capability registry — code, not data
    roles.py          Per-bank role rows and permission lookup
    llm.py            Gemini REST (httpx, no SDK) with a strict context-only prompt
    telegram.py       Bot API send/setWebhook
    channels.py       The honest channel catalogue for Settings — live, and what each costs
    handoff_webhook.py Deliver escalations into a bank's existing contact-centre tool
    i18n.py           Assistant strings in en/am/om/ti/so, with translator notes
    models.py         Bank, Document, Chunk, Conversation, Message, Handoff, Faq,
                      User, Role, RolePermission, TellerSession, AuditLog
    seed*.py          Demo Bank Ethiopia (15 docs) + CBE / Dashen / Awash prospect tenants
    evals.py          Golden-question eval runner
    static/           widget.html (embeddable chat + call), admin.html (the whole console)
  migrations/         Alembic environment + versions (0001 baseline .. 0022 head)
  docs/               video-teller.md, per-person-logins.md
  tests/              1,107 tests: tenancy, guardrails, retrieval, teller lifecycle,
                      verification, departments, FAQ, ingest, i18n, permissions, evals
  .github/workflows/  CI: ruff + mypy strict + pytest + evals + migration round-trip + Docker
```

## Language notes

- Ethiopic script is detected as Amharic, with a Tigrinya orthographic tell
  (the ኣ series) to separate the two; Oromo/Somali use keyword lists. Users can
  also pin a language in the widget.
- EN and AM strings are reviewed; **OM, TI, SO strings are first drafts and
  must go through linguist review** before any bank pilot. `i18n.py` carries
  `_NOTES` for translators.

## Demo data disclaimer

`seed.py` creates the fictional **Demo Bank Ethiopia** with illustrative
figures only, deliberately not branded as any real institution.

**The `cbe`, `dashen` and `awash` tenants are private pitch-demo prototypes,
not live public products.** Each renders a mandatory disclaimer banner in the
widget. Making one of them "live" means signing a deal with that bank and
loading their real verified content — never flipping a switch on the existing
prototype. See `CLAUDE.md` and the `SOURCES*.md` files, which cite every figure
with a pull date.

## What's next

Short version — the full roadmap is in `CLAUDE.md`:

- **Phase 2, in progress:** first paying pilot. Bulk import is the onboarding
  path; analytics and the handoff console have shipped; CSV/print export and
  embedding retrieval behind the same `retrieve()` interface are open. Hosting
  must move in-country (Ethio Telecom ECS) **before** real customer chat logs
  exist — chat content is personal data under Proclamation 1321/2024 Art. 22.
- **Phase 3:** authenticated account servicing — OTP session, read-only first,
  via the bank's middleware team. INSA certification.
- **Phase 4:** WhatsApp Business and USSD/IVR for feature phones; the financial
  education layer.
