# Olink Bank Assist — overview

A white-label AI banking assistant for Ethiopian banks and microfinance
institutions, by Olink Technologies. Each bank deploys a branded assistant its
customers talk to about accounts, transfers, loans, fees and saving — in
Amharic, Afaan Oromo, Tigrinya, Somali, Swahili or English — over seven channels: the
web widget, Telegram, Viber, WhatsApp, Facebook Messenger, Instagram Direct
and SMS.

## The one constraint everything follows from

**The assistant never moves money and never sees an account.** Core banking
stays on the teller's own screen, under the bank's own approvals. There is no
code path that does otherwise; a module-level assertion in
`bankassist/teller.py` refuses to start the service if one is added
(ADR-0001). This is what makes an AI safe to put in front of banking
customers, and it is why the answer to "what happens when the bot can't
help?" is a person, not a ticket.

## The three tiers of an answer

Every customer message resolves into exactly one of these, in order. The
order is the product (ADR-0006).

| Tier | What answers | Cost |
|---|---|---|
| 1 — Curated | The bank's own written answer, verbatim | zero — no retrieval, no model call |
| 2 — Retrieved | BM25 over the bank's knowledge base, optionally phrased by Gemini | one model call |
| 3 — Live teller | A real person on a LiveKit call, with the whole transcript | a human minute |

Tier 3 is what makes this a banking channel rather than an FAQ bot. Tier 1 is
what keeps the model bill from scaling with traffic on the questions
everybody asks.

## Who runs on it

Four tenants are seeded in production (`demo`, `cbe`, `dashen`, `awash`).
`demo` is a fictional bank; the other three are **private pitch-demo
prototypes, not live public products** — each carries a mandatory disclaimer
banner, and making one "live" means signing a deal with that bank first
(ADR-0009). The curated-FAQ corpus (160 answers) belongs to the `dashen`
tenant.

## Why this wins in Ethiopia

1. **Data residency is law** — Proclamation 1321/2024 Art. 22 requires
   in-country storage; Olink has the Ethio Telecom ECS deployment path and
   INSA-certification experience. Foreign SaaS vendors can't easily comply.
2. **Channel reality** — Ethiopian banks already run Telegram presences;
   the diaspora is on Viber and WhatsApp; SMS reaches customers with no
   smartphone at all. All seven adapters are built; each goes live on a
   credential (see `integrations/`).
3. **The language gap** — tens of millions of new digital-banking users think
   in Amharic or Afaan Oromo while bank support runs English-first. Every
   string in this product ships in six languages, verified by parity tests.

## Where the truth lives

- Operational state, gotchas, current phase: `CLAUDE.md` (the agent briefing)
- Why each load-bearing decision was made: `decisions/`
- How to operate it: `runbooks/`
- The live service: `https://bankassist-430565798339.us-east1.run.app`
  (`GET /health` reports the deployed revision and LLM backend)
