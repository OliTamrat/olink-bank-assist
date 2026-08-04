# Olink Bank Assist — Phase 1 MVP

A **white-label AI banking assistant for Ethiopian banks**. Each bank gets a
branded assistant its customers can talk to — in **Amharic, Afaan Oromo,
Tigrinya, Somali, or English** — about accounts, transfers, loans, fees,
saving, and general financial education, over a **web chat widget** or a
**Telegram bot**.

This is the Phase 1 sales-demo MVP: knowledge-base Q&A only, no customer
account access, no PII beyond the chat text itself. The full multi-phase
product plan lives in `CLAUDE.md`.

## Safety doctrine (non-negotiable)

Borrowed from the dispatch agents and tightened for banking:

1. **Tool output is truth.** Answers come from the bank's own knowledge base
   (BM25 retrieval). With a Gemini key, the model is instructed to answer only
   from retrieved context; with no key, the assistant returns the retrieved
   content verbatim (extractive mode). It never free-associates rates or fees.
2. **Allowlist, not blocklist.** Only greeting / product-question /
   investment-education intents are answered autonomously. Account-specific
   requests get a fixed security template; complaints go straight to a human
   handoff. Intent rules are deterministic regexes — the safety floor never
   depends on a model.
3. **Education, never advice.** Investment questions always carry the
   "general education, not personal investment advice" disclaimer, in the
   user's language. The system prompt additionally forbids personalized
   recommendations.
4. **Unknown means handoff.** If retrieval finds nothing informative, the
   assistant says it doesn't know and files a `Handoff` row the bank sees in
   the admin panel — every knowledge gap becomes a content task.
5. **Multi-tenant from day one.** Every query filters by `bank_id`; tests
   assert cross-tenant isolation for documents, chats, conversations, and
   admin tokens.
6. **Audit log.** Handoffs and every admin mutation write to `audit_log`
   (actor / action / entity_type / entity_id / metadata).

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m bankassist.seed        # prints the demo admin token
.venv/bin/python -m uvicorn bankassist.api:app --port 8100
```

- Widget: <http://localhost:8100/widget?bank=demo>
- Admin panel: <http://localhost:8100/admin> (slug `demo` + the printed token)
- API docs: <http://localhost:8100/docs>

Run tests: `.venv/bin/python -m pytest`

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `BANKASSIST_DATABASE_URL` | `sqlite:///bankassist.db` | SQLAlchemy URL (Postgres in prod) |
| `GEMINI_API_KEY` | unset | Enables LLM answers; unset = extractive fallback |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Generation model |
| `APP_BASE_URL` | `http://localhost:8100` | Public URL, used for Telegram webhooks |

The assistant is **fully demoable with no API key** — extractive mode quotes
the knowledge base directly. Add a Gemini key and answers become conversational
without changing the safety properties (context-only prompting + fallback on
any model failure).

## Connecting a Telegram bot

1. Create a bot with @BotFather, copy the token.
2. `POST /admin/api/{slug}/telegram/connect` with `{"bot_token": "..."}` and
   the `X-Admin-Token` header. This stores the token, mints a per-bank webhook
   secret, and registers `{APP_BASE_URL}/webhooks/telegram/{slug}` with
   Telegram (requires the service to be reachable over HTTPS).
3. Incoming updates are verified against the secret
   (`X-Telegram-Bot-Api-Secret-Token`, constant-time compare) — same
   fail-closed doctrine as the dispatch cron secret.

## Architecture

```
olink-bank-assist/
  bankassist/
    api.py         FastAPI app: chat, widget/admin pages, Telegram webhook, admin CRUD
    agent.py       Orchestration: classify -> guardrails -> retrieve -> answer
    classifier.py  Language detection + rules-based intent classification
    retrieval.py   Dependency-free BM25 over per-bank knowledge chunks
    llm.py         Gemini REST (httpx, no SDK) with strict context-only prompt
    telegram.py    Bot API send/setWebhook
    i18n.py        Assistant strings in en/am/om/ti/so
    models.py      Bank, Document, Chunk, Conversation, Message, Handoff, AuditLog
    seed.py        Demo Bank Ethiopia + 13-document knowledge base (EN + AM)
  static/          widget.html (embeddable chat), admin.html (KB/convos/handoffs)
  tests/           29 tests: tenancy, guardrails, retrieval, i18n detection, webhook
```

Retrieval is deliberately lexical (BM25) for the MVP: zero dependencies, works
offline, and handles Ge'ez-script text. `retrieve()` is the single entry point
— swapping in embeddings in Phase 2 touches nothing else.

## Language notes

- Ethiopic script is detected as Amharic, with a Tigrinya orthographic tell
  (the ኣ series) to separate the two; Oromo/Somali use keyword lists.
  Users can also pin a language in the widget.
- EN and AM strings are reviewed; **OM, TI, SO strings are first drafts and
  must go through linguist review** (same TSV workflow as Onekof) before any
  bank pilot.

## Demo data disclaimer

`seed.py` creates the fictional **Demo Bank Ethiopia** with illustrative
figures only. It is deliberately not branded as any real institution. For a
sales demo against a real prospect, load their public website content as
documents via the admin panel.

## Phase 2+ (full roadmap in CLAUDE.md)

- Real bank pilot: their knowledge base, their brand, analytics dashboard
  (deflection rate, top questions, language mix).
- **Deploy in-country** (Ethio Telecom ECS, same pattern as Onekof Tier 1)
  once real customer chat logs exist — chat content is personal data under
  Proclamation 1321/2024 Art. 22.
- Embedding retrieval, LLM intent refinement above the rules floor.
- Phase 3: authenticated account actions (OTP session, read-only first),
  INSA certification, human-agent console.
