# ADR-0032 — USSD rides the bank's short code, and starts as a menu

**Status:** accepted · **Date:** 2026-08-14

## Context

USSD reaches the customers no other channel in this product does: no
smartphone, no data, no app. In Ethiopia that is not a niche, and it is the
segment least served in Amharic, Afaan Oromo, Tigrinya and Somali — which is
where this product's advantage actually lies.

The full design is `docs/integrations/ussd.md`. This ADR records the two
choices the founder made on 2026-08-14 and the reasoning that will otherwise be
re-litigated the first time someone reads that document.

## Decision 1 — ride the bank's existing short code

**Use the number the bank's customers already dial, and add a menu code to it
as part of the pilot agreement. Do not apply for a separate short code.**

Every Ethiopian bank already runs USSD banking on a memorised number — Awash
`*901#`, Dashen `*996#`, CBE its own. Each of those carries an Ethio Telecom
agreement, an approved short code, and years of customer habit that cost
nothing to inherit and cannot be bought.

"Add an option to the menu you already run" is a smaller ask than a new short
code: no new regulatory approval, no new telecom contract, and the counterparty
is the bank rather than the regulator. A separate `*8xx#` would be a number
nobody knows, competing for memory with the one they use every week — and the
product would be paying, in customer confusion, for the privilege of owning it.

The technical consequence is deliberate and good: the bank's own USSD platform
becomes the gateway, so the integration is with *their* vendor rather than with
Ethio Telecom directly. That is the same counterparty as the SMS aggregator
agreement, and it is one where the bank is motivated.

### What this costs

Dependence on the bank's USSD vendor for the callback contract, and a menu
position we do not control. Accepted: neither is worth a separate short code
that customers would have to learn.

## Decision 2 — menu-only for v1

**Ship the numbered menu, built from the bank's published `Faq` rows. Defer
free-text entry until session data shows anyone would use it.**

Running the agent on USSD fails twice over, independently:

- **Latency.** Gateways expect an HTTP response in well under ten seconds while
  holding a radio session open. The agent path is classify → retrieve → Gemini:
  fine on a good day, not guaranteed on a bad one, and a timeout here is not a
  slow page — it is a dead session with nothing on screen.
- **Keyboards.** Nobody types "ወለድ ስንት ነው" on a T9 keypad to ask about an
  interest rate. Free text is the wrong *primary* input even where the script
  renders perfectly.

Both are answered by machinery that already exists. `Faq` rows are short,
bank-written, per-language, published per row, and served verbatim with no
model in the path — kept in their own table rather than as flagged `Document`
rows precisely so "may we quote this exactly" can never be one bad query away
from serving unreviewed material (see the `Faq` docstring in `models.py`).
A numbered menu of a bank's own published answers writes itself,
responds in milliseconds, and cannot hallucinate — on the one channel where a
timeout is fatal and a wrong number is unrecoverable.

This also gives the curated-answer loop its first customer-facing payoff. It
has been an internal quality tool; here, a bank that writes good curated
answers gets a good USSD menu for free.

### What this costs

The differentiator. "Ask anything in your own language" is the pitch, and a
menu is not that. Accepted on sequencing grounds rather than on principle: the
free-text design (deadline-raced against the extractive BM25 answer the product
already produces when no LLM is configured) stays in `ussd.md` and is expected
to ship second, informed by real session data about whether anyone types.

## What was measured before deciding

`scripts/ussd_budget.py`, added with this decision, computes the per-language
screen budget from the repo's own string tables. Two results changed the design
and neither was guessable:

**Ge'ez is denser than Latin.** Amharic and Tigrinya run ~0.68× the character
count of their English source, so a 91-character UCS-2 screen carries about 134
English characters of meaning. Afaan Oromo, Somali and Swahili get 182-character
screens but expand 1.11–1.19×. All six land within a factor of ~1.4, so **one
screen budget serves every language** — roughly 133 English characters — rather
than the two divergent layouts the naive "91 vs 182" reading implies.

**A decorative dash costs half a screen.** The Latin-script languages are
GSM-7 clean in their own letters; every offender found in them is punctuation
*we* chose (`—`, `…`, `·`, an emoji in the language-signal greeting). One of
those forces the whole message to UCS-2, halving 182 characters to 91 — and it
does not look like a bug, because the text still sends. The GSM-7 normaliser is
therefore load-bearing, and is the cheapest capacity doubling on the channel.

## Consequences

- **USSD stays out of `channels.CATALOGUE` until the adapter exists.** An
  eighth row visible to every prospect tenant, promising code that is not
  written, is worth less than the catalogue's invariant that nothing in it is
  `PLANNED`. `test_a_proposed_integration_page_says_so_until_it_is_in_the_catalogue`
  holds the page and the catalogue in agreement in both directions.
- **`_channel_reply()` will need splitting.** USSD returns its reply as the
  HTTP response body rather than through a `send` callable; forcing it through
  that signature would mean a `send` that appends to a list the caller reads.
  `ussd.md` §3 proposes extracting the shared middle instead.
- **Two measurements remain open** and neither blocks the other: whether cheap
  handsets render Ge'ez, and whether the gateway sends accumulated input. The
  second, if accumulated, deletes the session table before it is written.
- **No cost figures are stated anywhere.** That is the mistake ADR-0031's
  sibling correction (PR #163) had to undo on the Viber page; the numbers live
  in the bank's own Ethio Telecom agreement.
