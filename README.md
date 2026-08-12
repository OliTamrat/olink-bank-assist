# Olink Bank Assist

**Your bank's front door, in your customer's language — with a real teller one
tap away.**

A white-label AI banking assistant for African banks and microfinance
institutions, built first for Ethiopia and expanding across East Africa.
Customers ask about accounts, transfers, loans, fees and saving in **Amharic,
Afaan Oromo, Tigrinya, Somali, Swahili or English**, over the channel already
on the phone they already own — a **web chat widget**, **Telegram**,
**Viber**, **WhatsApp**, **Facebook Messenger**, **Instagram Direct** or
**SMS**. When the assistant cannot answer, or must not, the customer is handed
to **a real bank teller on a live call inside the same conversation**, with
the whole transcript already in front of them.

It is built on one hard constraint, and every other design decision follows
from it: **the assistant never moves money and never sees an account.** Core
banking stays where it belongs — on the teller's own screen, under the bank's
own approvals. There is no code path that does otherwise, and a module-level
assertion refuses to start the service if one is ever added.

That constraint is what makes an AI safe to put in front of banking customers.
It is also why the answer to *"what happens when the bot can't help?"* is a
person, not a ticket.

|  |  |
|---|---|
| **Six languages** | Amharic, Afaan Oromo, Tigrinya, Somali, Swahili, English — detected per message, not per session |
| **Seven channels** | Web widget, Telegram, Viber, WhatsApp, Messenger, Instagram, SMS — one conversation core, every adapter built |
| **Three ways to answer** | The bank's curated words, its own documents, or a live human |
| **Never invents a number** | An answer carrying a figure with no source fails the eval gate |
| **Multi-tenant** | Every query filters by bank; cross-tenant isolation is asserted in tests |
| **Data-residency ready** | Built for Proclamation 1321/2024 Art. 22 — deployable in-country |
| **Runs without an API key** | Extractive mode quotes the knowledge base directly; add a model and it gets conversational, not less safe |

Live at `https://bankassist-430565798339.us-east1.run.app`, deployed from
`main` by GitHub Actions on every CI-green push. The full product plan,
architecture doctrine and roadmap live in `CLAUDE.md`.

---

## One conversation, seven channels

Omni-channel is not a list of logos here — it is an architectural decision.
Every messaging surface runs through **one conversation core**
(`_channel_reply()` in `api.py`): the same language detection, the same
guardrails, the same curated answers, the same escalation desks, the same
live-teller handoff. A channel adapter is *transport only* — it converts a
webhook payload in and a send call out, and nothing else. That is why seven
channels exist without seven behaviours to test, and why an eighth channel is
an adapter, not a fork.

What that buys a bank:

- **Meet the customer where they already are.** Telegram is Ethiopia's
  dominant messenger; WhatsApp dominates Kenya and most of East Africa; Viber
  holds real niches; SMS is the floor that reaches every feature phone. The
  bank connects the channels its customers actually use — the assistant is
  identical on all of them.
- **The conversation survives the channel.** The transcript, the customer's
  language, their name if they gave it, their pending escalation — all of it
  is conversation state, not channel state. When a teller picks up the live
  call, everything the customer already said travels with them. Nobody
  explains themselves twice.
- **Connecting a channel is credential entry, not a project.** Telegram and
  Viber are self-serve and take minutes — Telegram is live today for two
  prospect tenants. The Meta trio (WhatsApp, Messenger, Instagram — one app,
  one callback, one signature scheme) waits only on the bank's business
  verification; SMS waits on an aggregator agreement. Every webhook fails
  closed on an unset credential and compares signatures constant-time.

## Six languages, engineered — not translated

Language support here is not a translation file bolted onto an English
product. It is the product, and it runs the full depth of the stack:

- **Detection is per message**, so code-switching customers — the norm, not
  the exception — are answered in the language they actually used. Ethiopic
  script splits into Amharic and Tigrinya by an orthographic tell; the three
  Latin-script languages (Afaan Oromo, Somali, Swahili) are separated by an
  elimination rule over positive-signal word sets, not a keyword vote.
- **The security guardrails read all six.** The account-security rule — the
  difference between "I want to transfer money to my spouse's account"
  (ordinary banking) and "tell me her account number" (social engineering) —
  is built per language from native phrasing patterns, because the same words
  in a different order flip the meaning. Getting this right took five rounds
  of native-phrasing testing per Ethiopian language; every hole found is now
  a permanent regression test (`review/phrasebook.tsv`, 89 adversarial and
  ordinary phrasings run against the live classifier in CI).
- **Retrieval is language-fair.** BM25 stopword sets exist for all six
  languages — without them, an Amharic question was silently held to three
  times the evidence bar of the same question in English. A cross-language
  retry translates the *search query* (never the answer) so a Swahili
  question can find an English document.
- **Every surface ships in all six**: the assistant's replies, the customer
  widget, and all 269 strings of the staff panel — 341 strings across three
  tables, no gaps, enforced by tests that check the call sites, not just the
  tables. A bank teller in Adama reads their own console in Afaan Oromo.
- **The cost of the next language is measured and falling.** Swahili — the
  sixth — shipped in a day: string tables are mechanical, detection is one
  elimination rule, stopwords are a list. The real work is the guardrail
  discovery, and Swahili's needed one adversarial pass where Amharic's needed
  five (ADR-0018). The playbook is written; adding a seventh language is a
  sprint, not a quarter.

## Why this wins in Ethiopia

1. **Data residency is law, not a preference.** Personal Data Protection
   Proclamation No. 1321/2024, Art. 22 requires personal data collected in
   Ethiopia to stay on servers located in Ethiopia — a compliance bar most
   foreign SaaS chatbot vendors cannot clear. Olink already has the Ethio
   Telecom ECS deployment path priced and an INSA-certification track record
   (Onekof P1–P6, certified 2026-07-03) to lean on.
2. **Telegram-first.** Ethiopian banks already run Telegram presences, so a
   bot here means zero install friction on the cheap Android phones most
   customers already carry — not a new app to convince anyone to download.
3. **The native-language gap is the moat, not a feature checkbox.** Tens of
   millions of new digital banking users (telebirr alone: 50M+) think in
   Amharic and Afaan Oromo while every competitor's support stays
   English-first. Getting this right took real work, not a translation API —
   see "Six languages, engineered" above.
4. **Channel-to-human continuity is real, but it is not the whole story.**
   [Glia](https://www.glia.com) already sells exactly that mechanic — a
   conversation surviving a handoff from AI to a live human — at scale, to
   700+ US banks and credit unions. What Glia does not have is Telegram as a
   first channel, native-language guardrail depth for Ethiopian languages, an
   in-country data-residency posture, or a price and deployment speed a
   single bank or MFI can say yes to without an enterprise procurement cycle.
   That combination — not the handoff mechanic alone — is the whitespace.

## Why East Africa is next

Swahili is not a sixth checkbox — it is the region's own language, spoken by
roughly 200 million people across Kenya, Tanzania, Uganda, Rwanda and eastern
DRC, and it shipped precisely because the expansion path runs through East
Africa first (ADR-0019):

- **The appetite is proven, locally.** East African banks already build their
  own bots — Equity Bank's EVA is the visible example — which is the market
  saying yes to the category. What exists today is the "before" picture:
  single-channel, bank-built, English-first, with no evidence of
  cross-channel continuity or a live human reachable inside the same
  conversation. That gap is the pitch, and it is observed, not guessed.
- **The regional focus is a deliberate call, on the record.** A
  Hausa/Yoruba/Igbo bundle for Nigeria was scoped, and parked — not because
  the market is small (it isn't; Nigerian banks run the continent's most
  visible bot precedents, from Zenith's ZiVA to UBA's Leo), but because depth
  in the region Swahili already anchors beats a second regional jump made
  immediately after the first. Sequencing, not retreat — the record is
  ADR-0019 and `docs/market-position.md`, costs stated plainly.
- **The same structural advantages travel.** Data-protection law with
  residency provisions is spreading across the region; the multilingual
  guardrail playbook, the channel adapters and the teller handoff work
  unchanged; and every East African market shares the property that made
  Ethiopia the right start — a huge population entering digital banking in
  their own language, served by English-first tools.

## The vision: a continent, one conversation at a time

The long game is a pan-African conversational banking layer, built outward
from proof rather than announced from a slide:

1. **Prove it in Ethiopia** — the hardest market by language (four languages
   that mainstream NLP barely covers, engineered from a standing start) and
   the strongest moat by law (Art. 22 residency + INSA certification). A
   product that clears Ethiopia's bar is over-built for everywhere else, in
   the best way.
2. **Deepen through East Africa** — Swahili anchors the region; each next
   market is channel credentials, a knowledge-base import and brand colours,
   not a rebuild. Multi-tenancy, per-bank isolation and white-labelling are
   in the foundation, asserted by tests, so one deployment serves many
   institutions without their data ever touching.
3. **Then west, then north.** The Nigeria bundle is parked with the market
   case intact, waiting on the regional call — not cancelled. Arabic is
   sequenced after it, deliberately: right-to-left is real engineering across
   the widget and the admin panel, not a string table, and it will be done
   properly or not yet.
4. **Beyond banking, the same shape.** Insurance Q&A, telecom support, MFI
   servicing and government citizen services all share the pattern this
   product already implements: a hard boundary around what a license is
   required to say, multilingual customers, and a human who must be reachable
   when the machine must stop. The account guardrail *is* the claims
   guardrail with different nouns.

Addis Ababa itself is part of the plan: as the African Union's headquarters
city, real traction in Ethiopia puts this product in regular contact with
continental banking and policy leadership that would otherwise take years of
cold outreach to reach — a network effect available nowhere else on the
continent.

Stated honestly, because the credibility of the rest depends on it: **no bank
has signed yet.** The CBE, Dashen and Awash tenants are unauthorized internal
prototypes built from public information, each carrying a mandatory
disclaimer (ADR-0009). What makes the vision more than a slide is the depth
already built underneath it — the guardrail rigor, the language engineering,
the live-teller traffic already verified against real WebRTC sessions — and
that is the order the story is told in: the concrete thing first, the map
second.

---

## Documentation

`docs/` is this product's OKM (Olink Knowledge Management) tree —
`overview.md`, `architecture.md`, `runbooks/`, `integrations/`, and
`decisions/` (19 ADRs recording *why* each load-bearing choice was made, from
"the assistant never moves money" to this week's language-expansion order).
Checkable claims there are graded against the actual code by
`tests/test_docs_truth.py` in CI, not just written down. It's also the
knowledge base behind **Ask OKM**, an internal tenant of this same product
that answers questions over the whole Olink fleet's documentation
(`bankassist/seed_okm.py`, ADR-0015).

All seven Olink products follow this same taxonomy and aggregate into one
searchable portal at [`olink-knowledge`](https://github.com/OliTamrat/olink-knowledge).

*A product of [Olink Technologies](https://olinkgo.us).*

## The three tiers of an answer

Every customer message resolves into exactly one of these, in this order.
The order is the product.

| Tier | What answers | Cost | When |
|---|---|---|---|
| **1 — Curated** | The bank's own written answer, verbatim | zero — no retrieval, no model call | The question matches a curated FAQ exactly |
| **2 — Retrieved** | BM25 over the bank's knowledge base, optionally phrased by Gemini | one model call | Retrieval finds something informative |
| **3 — Live teller (ITA)** | A real person, on a LiveKit call, with the whole transcript | a human minute | Anything account-specific, anything unknown, anything the customer asks a person for |

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

## The live teller — ITA (Interactive Teller Assistant)

`docs/video-teller.md` is the design document. In short:

**On the name.** The industry term for a video link to a remote teller is
*ITM — Interactive Teller **Machine***, and that is deliberately not what this
is called. An ITM is a physical kiosk: hardware, capex, a procurement cycle, a
vendor category we are not in. We ship software that reaches a customer on the
phone already in their hand. Being filed under the wrong category is not a
cosmetic problem — it is being evaluated against a purchase we are not
offering. **A** for **Assistant**, not Agent: in Ethiopia "agent" means agent
banking (a shop doing cash-in/cash-out), and in 2026 "agent" also reads as
autonomous AI — the worst possible misread for the one feature whose entire
point is that a human being answers.

**ITA is an internal and sales name; it never appears in the product.**
Customers see "Connect to a teller", the dashboard says "Live". *Teller* is
the word an Ethiopian bank customer already owns, and asking them to learn an
acronym at the moment they want help trades their vocabulary for ours.

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

## The operator console

Everything a bank's own staff use lives in one panel (`static/admin.html`) —
no separate tool, no second login. What's in it, beyond the sections below
with their own deep dives:

- **Overview** — is the assistant actually working: conversations, deflection
  rate (customers resolved without a person), languages spoken, channel mix.
  A rate with no denominator is reported as `null`, never `0` — "0%
  deflection" on a fresh tenant would be a lie told by a division.
- **Content Gaps** — what to write next: every unanswered question grouped by
  wording and ranked by frequency, split from questions the assistant *could*
  answer from general banking knowledge but the bank hasn't written its own
  version of yet. This is the thing a plain FAQ bot cannot give a bank at
  all — a real, ranked list of what its customers ask and nobody can answer.
- **Global search** — one box across conversations, escalations, the
  knowledge base and curated answers, with results opening straight into the
  same transcript and editor views the rest of the panel already uses.
- **Live queue + teller performance** — the real-time call queue a teller
  works from, plus calls-per-teller and average-wait analytics for whoever
  manages the floor.
- **Team & roles** — twelve fine-grained permissions (`permissions.py`),
  assignable per person per bank — see "Who can do what" below.
- **Channels** — connect Telegram, Viber, WhatsApp/Messenger/Instagram or SMS
  by pasting a credential; see "Connecting a channel" below.
- **Audit log** — every admin mutation and handoff action, actor and
  timestamp, never the chat content itself.

Built in **six languages from the first line of interface chrome**, not
retrofitted — see "Language notes" below.

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

### Translating them

The 160 **Dashen** answers live in the production database in English only.
They are the last thing a customer can reach in English after asking in
Amharic, and they are the one translation that is a second piece of
*bank-approved copy* rather than a convenience — a curated answer is served
verbatim, with no model call and no gate after it.

```bash
python scripts/faq_export.py dashen          # -> review/faq-dashen.tsv
# fill in the language columns
python scripts/faq_import.py dashen          # dry run: prints every change
python scripts/faq_import.py dashen --write  # applies it, as DRAFTS
```

Both halves need the production database. The importer **writes drafts only**,
whatever the sheet says — approving is a separate act in the admin panel,
because a translation going straight to the live path in a language nobody on
the team reads is exactly what the review step exists to prevent.

`POST /faq/translate` does the same job in bulk with Gemini. It is an
accelerator, not a prerequisite: the sheet loop needs no model at all.

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
- Pasted content is a first-class input, not a fallback. Most Ethiopian bank
  sites render in the browser, so both the URL fetch and View Source see the
  same empty shell. **Expand every accordion, then F12 → right-click `<html>`
  → Copy → Copy outerHTML**, and paste that. Ctrl+A / Ctrl+C also works and is
  easier, but a text selection silently drops anything inside a collapsed
  panel — and on a bank site the collapsed panels are usually where the
  eligibility rules and fee tables live. `diagnose()` tells the operator which
  situation they are in rather than leaving them to guess.
- The URL fetch is **SSRF-safe by construction**: https only, no credentials,
  no IP literals at all, no localhost, redirects not followed, size and time
  caps. Known limit, stated in the docstring: a hostname that *resolves* to a
  private address still gets through.

**A bank's public website is a brochure, not a knowledge base.** Checked
against CBE's live site: product pages carry a two-sentence definition and a
grid of cards that link onward, with the real substance — eligibility,
benefits, target customers, the service list — folded into collapsed
accordions. That is a page built to route a visitor to a button, not to
answer a question. Import earns its keep on the pages that *do* have prose,
but the corpus for a real pilot comes from what a bank already gives its own
staff: call-centre scripts, product manuals, branch circulars, training
material. **Ask for those in the pilot conversation; do not plan onboarding
around scraping the website.**

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
baseline, head is **0025**. `BANKASSIST_DATABASE_URL` is the single source of
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
| `APP_BASE_URL` | `http://localhost:8100` | Public URL, used to build every channel's webhook/callback |
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

## Connecting a channel

Every messaging adapter is built; connecting one is credential entry. The
full per-channel story — what to create, what each vendor signs, and what is
still gated on a business account — lives in `docs/integrations/`.

| Channel | Connect | Waits on |
|---|---|---|
| Telegram | `POST /admin/api/{slug}/telegram/connect` with a @BotFather token | nothing — minutes. Live for CBE and Dashen |
| Viber | `POST /admin/api/{slug}/viber/connect` with a partners.viber.com token | nothing — minutes |
| WhatsApp / Messenger / Instagram | `POST /admin/api/{slug}/meta/connect`, then paste the returned callback URL + verify token into Meta's dashboard | Meta business verification and review |
| SMS | `POST /admin/api/{slug}/sms/connect` with the aggregator's send URL | an aggregator agreement (Ethio Telecom) |

Every webhook fails closed on an unset credential and compares
signatures/secrets constant-time. One callback serves all three Meta
products — they are one app with one signature scheme.

## Architecture

```
olink-bank-assist/
  bankassist/
    api.py            FastAPI app: chat, widget/admin pages, channel webhooks, admin + teller API,
                       global search
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
    viber.py          Channels API send/signature — Viber reports errors inside HTTP 200
    meta.py           WhatsApp + Messenger + Instagram: one app, one callback, one signature
    sms.py            Aggregator contract: generous inbound parsing, numbered billed segments
    channels.py       The honest channel catalogue for Settings — live, and what each costs
    handoff_webhook.py Deliver escalations into a bank's existing contact-centre tool
    i18n.py           Assistant strings in en/am/om/ti/so/sw, with translator notes
    models.py         Bank, Document, Chunk, Conversation, Message, Handoff, Faq,
                      User, Role, RolePermission, TellerSession, AuditLog
    seed*.py          Demo Bank Ethiopia (15 docs) + CBE / Dashen / Awash prospect tenants
    evals.py          Golden-question eval runner
    static/           widget.html (embeddable chat + call), admin.html (the whole console)
  migrations/         Alembic environment + versions (0001 baseline .. 0025 head)
  docs/               The knowledge base: overview, architecture, runbooks/,
                      integrations/, decisions/ (19 ADRs) — see docs/README.md
  tests/              1,450+ tests: tenancy, guardrails, retrieval, teller lifecycle,
                      verification, departments, FAQ, channels, i18n, permissions, evals
  .github/workflows/  CI: ruff + mypy strict + pytest + evals + migration round-trip + Docker;
                      deploy on green push to main; manual branch pruning
```

## Language notes

Six languages, and that means the whole product rather than the replies
alone. **369 strings across three tables, no gaps:**

| Table | Strings | Covers |
|---|---|---|
| `strings.json` | 20 | what the assistant says |
| `ui_strings.json` | 52 | the widget's buttons and labels |
| `admin_strings.json` | 297 | the staff panel, teller console included |

- Ethiopic script is detected as Amharic, with a Tigrinya orthographic tell
  (the ኣ series) to separate the two. Afaan Oromo, Somali and Swahili — the
  three Latin-script local languages — are separated by an elimination rule
  over positive-signal word sets, not a fixed keyword vote; adding Swahili
  turned this from a two-way tie-break into a genuine three-way one
  (`classifier.detect_language`). Users can also pin a language in the
  widget.
- **The classifier reads all six too, not just the replies.** Amharic and
  Tigrinya share a script and almost no spellings — ሂሳብ is the Amharic
  account, ሕሳብ the Tigrinya one — so the Amharic rules matched no Tigrinya
  sentence at all until the guardrail was extended. A customer writing in
  Tigrinya could report theft and file no complaint. `review/phrasebook.tsv`
  is the regression suite for this (89 rows across all six languages) and
  `scripts/check_phrasebook.py` runs it against the live classifier.
- **EN and AM strings are reviewed; OM, TI, SO and SW are first drafts** and
  must go through linguist review before any bank pilot. That includes the
  classifier phrasings, not just the wording customers read — the review is
  load-bearing rather than cosmetic. Hand a reviewer
  `review/Olink_Bank_Assist_language_review.xlsx` — four sheets, generated
  from the live tables by `scripts/build_review_workbook.py`.
- **Swahili shipped as the sixth language, first-pass like Somali** (ADR-0018)
  — East Africa's own language, ~200M speakers across Kenya, Tanzania, Uganda
  and Rwanda. Discovery was measurably faster than the four Ethiopian
  languages needed (Swahili already has substantial representation in
  mainstream AI/NLP tooling), but it still needed real testing: the
  account-guardrail's "forgot PIN" rule had a genuine over-refusal bug — the
  Swahili conditional infix ("if I forget") collided with the forgot-verb
  stem — found and fixed by running the adversarial case, not by reading the
  regex.
- **Next language work stays regional.** The Hausa/Yoruba/Igbo (Nigeria)
  bundle is parked, not cancelled — near-term expansion is evaluated against
  East Africa's reach first, the region Swahili already anchors, before a
  second regional jump to West Africa (ADR-0019). `docs/market-position.md`
  has the full reasoning, including the real cost of that trade-off.
- **Not translated, deliberately:** proper nouns (Fayda, Telegram, WhatsApp),
  permission identifiers, per-tenant database content, and anything a customer
  typed. Ge'ez writes the Fayda name as ፋይዳ — transliteration, not
  translation.
- **The 160 curated Dashen answers are English-only.** That is the one
  remaining gap; see "Curated answers" above.

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
  path; analytics, Content Gaps, global search, the handoff console, the live
  teller and six-language coverage have all shipped. Open: embedding
  retrieval behind the same `retrieve()` interface, LLM intent refinement
  above the rules floor, the OM/TI/SO/SW linguist review, and splitting the
  Cloud Run runtime service account down to least privilege. Hosting must
  move in-country (Ethio Telecom ECS) **before** real customer chat logs
  exist — chat content is personal data under Proclamation 1321/2024 Art. 22.
- **Language expansion:** Swahili shipped 2026-08-12 as the sixth language.
  Next work stays inside East Africa before any West Africa jump — the
  Nigeria bundle (Hausa/Yoruba/Igbo) is parked, not cancelled (ADR-0019).
- **Phase 3:** authenticated account servicing — OTP session, read-only first,
  via the bank's middleware team. INSA certification.
- **Phase 4:** WhatsApp Business and USSD/IVR for feature phones; the financial
  education layer.
