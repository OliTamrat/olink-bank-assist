# ADR-0035 — A miss offers questions, not filing labels

**Status:** accepted · **Date:** 2026-08-15

## Context

When the knowledge base does not answer somebody, the assistant says so and
offers a few chips to tap rather than a dead end (`retrieval.suggest_topics`,
since the earliest version of the product). Those chips were **document
titles** — "ATM and Debit Cards", "Transfers to Other Banks and Wallets".

The founder's screenshots of CBE's own "Selam" bot on `combanketh.et` are what
made the difference visible. Selam offers follow-ups phrased as questions —
"SWIFT code for Commercial Bank of Ethiopia (CBE)". Ours offered filing labels.

**A question is a thing a customer taps. A topic is a thing they have to
translate back into a question first** — on the one screen where they have
already failed to be understood once. The customer who most needs the chip is
the one who could not phrase the question in the first place, and a label asks
them to do exactly the work they just failed at.

The material was already in the product and needed no new plumbing. `Faq`
holds real customer-phrased questions, per bank, per language, published, and
served **verbatim with no model in the path** (see the curated-answers section
of `CLAUDE.md`). Offering one and having it tapped is a closed loop: the chip's
text is exactly the lookup key, so a tap lands on the bank's own approved
answer.

## Decision

`retrieval.suggest()` replaces `suggest_topics()` as what the agent calls, and
runs a four-step cascade — first non-empty wins:

1. **A published FAQ question of this bank, in this language, that shares a
   content word with what was asked.** Best of all: the customer's own phrasing,
   and one tap from an approved answer.
2. **A near-miss document title** — unchanged behaviour. A *relevant* title
   beats an *irrelevant* question; relevance is worth more than shape.
3. **The most-served published questions**, when nothing matched at all. A
   cold-start menu of what people actually ask beats a list of the bank's
   longest documents.
4. **The broadest document titles**, as before, for a bank that has curated
   nothing.

`suggest_topics()` stays as steps 2+4 and keeps its tests: most tenants have
curated nothing and must not get a worse miss for it.

**One kind per turn, never a blend.** The reply text introduces the list with a
sentence, and a row mixing questions with filing labels makes whichever
sentence it chose wrong about half of what is under it. Hence the new
`related_questions` string ("In the meantime, you can ask me any of these:")
beside `related_topics`, in all six languages, picked by whether the first
suggestion carries a `faq_id`.

**Matching is deliberately not the retrieval scorer.** That one is tuned to
decide whether a chunk *answers* a question, over corpus statistics describing
documents rather than a table of one-line questions. Here the job is only "does
this share a subject with what was asked": a shared content word, ranked by how
many, then by `served`, then alphabetically so equal candidates do not swap
places between requests. Stopwords are dropped from the query side — "how" and
"my" appear in most questions any bank has published, so matching on one is not
a topic in common.

## Consequences

- **Nothing is generated.** A suggestion is still text the bank wrote, offered
  word for word; `Faq.question` is stored as a customer would type it, which is
  what makes handing it back safe. The safety doctrine's "suggestions are
  navigation, never answers" is unchanged — the wording in doctrine item 5 that
  said *document titles only* was describing the mechanism, not the rule.
- **Language is part of the filter, not a nicety.** A chip is tapped and its
  text becomes the next message, so a question in another language would take
  the reply with it — an English answer to somebody writing Amharic, through
  the one path with no gate after it.
- **Drafts are never advertised**, for the same reason they are never served.
- **Tenancy holds**: a question is scoped by `bank_id` exactly as a document is.
- **No guardrail moves.** A tapped chip is an ordinary message and runs the
  whole pipeline again, so a question a bank should never have published — "what
  is my account balance" — still gets the account refusal rather than its own
  curated answer. The curated lookup sits after every guardrail and being
  suggested changes nothing about that.
- **`served` counts servings, not offers.** Inflating it with chips nobody
  tapped would corrupt the one number that tells a bank whether curating more
  of these is worth an afternoon — and it is also the rank key in step 3, so it
  would corrupt the cold-start menu with its own output.
- **A bank with no curated answers sees no change at all**, which is currently
  every tenant except `dashen` and its 160 English answers.
- **This is the same machinery the USSD menu needs** (ADR-0032): a per-language
  list of published questions, offered as a numbered menu instead of chips. One
  build, two channels.
- **Cost:** the miss path now reads this bank's published questions and
  tokenizes them. It is the miss path only, bounded by what a bank has curated,
  and it replaces no cheaper work. If a tenant ever publishes questions in the
  thousands, this is where to add an index rather than the place to be
  surprised.

## References

- `bankassist/retrieval.py` — `suggest`, `suggest_questions`, `popular_questions`
- `bankassist/agent.py` — `suggestions_for`, `_offer_intro`
- `tests/test_faq_suggestions.py`
- ADR-0032 (USSD rides the bank's short code and starts as a menu)
- The roadmap item this closes, `CLAUDE.md` Phase 1, designed 2026-08-15
