# CBE Sales Demo — Prep Notes

**Status: demo-ready locally, not yet deployed.** Everything below works
today via `uvicorn` on your machine; see "Before the meeting" for what's
left to do it live in a browser you can hand someone.

## The 60-second pitch

"We built a working prototype of an AI assistant for CBE customers, using
CBE's own public information — in English and Amharic, answering the
questions your call center handles thousands of times a day. It's not
connected to CBE systems and it's not an official CBE product — it's a demo
of what's possible, built to show you rather than describe to you."

**Lead with the moat, not the chatbot.** Any vendor can demo a chatbot.
What most can't offer:
1. **Ethiopian data residency by design** — Proclamation 1321/2024 Art. 22
   requires personal data collected in Ethiopia to stay on servers in
   Ethiopia. We already have the Ethio Telecom Cloud deployment path and
   INSA-certification experience from our other platform (Onekof).
2. **Telegram-native** — no app install friction, works on any Android phone,
   and CBE customers are already there.
3. **It never guesses.** Ask it something outside the loaded knowledge base
   and watch it say "I don't know" and flag the question — instead of
   inventing a plausible-sounding wrong answer. This is the actual
   engineering difficulty in a banking chatbot, and it's the first thing to
   demonstrate live.

## Demo flow (5 minutes)

Run locally first: `python -m bankassist.seed_cbe && uvicorn bankassist.api:app --port 8100`,
then open `http://localhost:8100/widget?bank=cbe`.

1. **Point out the disclaimer banner first, unprompted.** "This banner is
   there on purpose — this is a prototype we built, not something live in
   CBE's systems. Full transparency." Builds trust before anything else.
2. Ask in English: *"What is the interest rate on a savings account?"*
   → leads with the real 7% figure, cites its source document.
3. Switch to Amharic, ask: *"የሞባይል ባንኪንግ እንዴት አስጀምራለሁ?"* (how do I
   activate mobile banking) → answers correctly in Amharic. This is usually
   the moment that lands — most banking chatbots are English-only.
4. Ask something it *can't* know: *"What's my account balance?"* → shows the
   security refusal, never claims account access it doesn't have.
5. Ask something *out of scope entirely*: *"Do you sponsor football
   tournaments?"* → shows the "I don't know, flagged for follow-up" behavior
   instead of a hallucinated answer. **This is the guardrail pitch — make it
   explicit**: "Every question it can't answer becomes a ticket your team
   sees. Nothing gets guessed."
6. If asked about integration: mobile banking activation, telebirr
   transfers, ATM cards, diaspora accounts, and loan eligibility are all in
   the knowledge base — invite them to ask their own question live.

## What to say if asked about accuracy

Some figures (exact fixed-deposit rates by term, precise transfer fee
tiers, ATM fee percentages) are deliberately **not** stated with specific
numbers in this prototype — public sources disagreed and we chose not to
guess. Say exactly that: *"We built this from your public website and public
reporting. Anywhere we weren't certain, we made the assistant vague rather
than wrong — the moment you give us your real, current rate sheet through
the admin panel, that becomes precise. That's the whole point of the
architecture: it only ever says what you tell it."* Full citation list is in
`SOURCES.md` if anyone wants to check a specific figure.

## Guardrails, in plain language (have these ready)

- It answers questions about products, fees (where confirmed), and
  how-to procedures — never personal account data.
- It never gives personal investment advice — only general education, with
  a disclaimer, and always suggests speaking to a licensed advisor.
- It never invents a number. If it's not in the knowledge base, it says so
  and creates a follow-up ticket instead of guessing.
- Every conversation and every "I don't know" moment is visible in the
  admin panel — it's not a black box.

## Before the meeting

- [ ] **Deploy it somewhere with a real URL** so you can send a link instead
      of demoing on a laptop (Cloud Run, same pattern as olink-dispatch —
      `bankassist.db` is SQLite by default, fine for a demo; set
      `BANKASSIST_DATABASE_URL` to Postgres if you want it to persist across
      redeploys). This is the single highest-leverage thing left to do.
- [ ] Optional: set `GEMINI_API_KEY` before the meeting — conversational
      mode reads noticeably better live than extractive mode, though
      extractive mode is completely fine and already demoed well.
- [ ] Skim `SOURCES.md` once so you can answer "where did this number come
      from" instantly if asked.
- [ ] Decide in advance what you're asking for at the end of the meeting —
      likely: a follow-up with their digital/innovation team, and access to
      their real product/rate sheet to replace the demo content.

## Do not

- Do not present this as CBE-endorsed or built with CBE's cooperation — it
  wasn't, and the disclaimer banner exists specifically so nobody in the
  room can later say they were misled.
- Do not let the Amharic content go out further (screenshots, decks shared
  without you present) without a native speaker sanity-check — it's good but
  unreviewed; fine for a live demo where you're present to field questions,
  riskier as a leave-behind artifact.
