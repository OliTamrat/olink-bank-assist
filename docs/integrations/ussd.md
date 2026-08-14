# USSD — proposed, not built

**Status: design only, 2026-08-14. No code exists.** Every other page in this
directory documents something shipped; this one documents something argued for.
It is here rather than in `decisions/` because it is a proposal, not a decision
— when it is accepted or rejected, that becomes an ADR and this page either
grows a "Connect" section or is deleted.

USSD is deliberately **absent from `channels.py`**. Adding it as `PLANNED`
would put an eighth row on the Channels page that every prospect tenant can
see, promising something with no code behind it — and the catalogue's current
invariant, that nothing in it is `PLANNED`, is worth more than an early
mention. It goes in the catalogue on the day the adapter does.

---

## 0. Read this before costing anything

**One number decides whether this project is what it looks like, and nobody
has measured it: whether a cheap Ethiopian handset renders Ge'ez on a USSD
screen.**

Two separate unknowns hide in there.

**Encoding is knowable and fine.** A USSD string is at most 182 octets. Latin
text packs into GSM 03.38 7-bit, giving ~182 characters per screen. Ge'ez has
no GSM-7 representation, so it goes as UCS-2 at two bytes per character —
about **91 characters per screen**. Tight, and workable: 91 characters is a
sentence, and a sentence per screen is what USSD is for.

**Rendering is not knowable from a desk.** Whether a 1,200-birr feature phone
sold in Adama ships an Ethiopic font, and whether its USSD dialog uses that
font, is a property of handsets in the field. It cannot be researched; it can
only be tested. If the answer is no, the customer sees boxes, and every
argument for this channel evaporates in the same second.

**The measurement.** Borrow three or four of the cheapest handsets actually
sold in Ethiopian kiosks, and have any party who already holds a short code
push one Amharic string to them. Half a day. Do it before writing a line of
this.

**If Ge'ez does not render**, the fallback is Latin transliteration —
`selam, endet nachehu` — which Ethiopians already use in SMS and chat every
day. That is not a defeat, but it *is* a different product: the pitch stops
being "your customers' own script" and becomes "your customers' own language,
in the alphabet their phone can draw". Decide that consciously rather than
discovering it in a pilot.

> This section is first because the Viber correction (ADR-0031's sibling, PR
> #163) cost a night: four files stated a vendor fact that had been false for
> eighteen months. The lesson generalises past vendors. **When a plan rests on
> one unmeasured fact about the physical world, measure it before designing
> around it.**

---

## 1. The core idea — USSD is the curated-answer channel

The obvious design is "run the agent, print the answer". It is wrong on this
channel, for two independent reasons that happen to have one shared fix.

**Latency.** USSD gateways expect an HTTP response in well under ten seconds,
and hold a live radio session open while they wait. The agent path is
classify → retrieve → Gemini. That is comfortably inside ten seconds on a good
day and nowhere near guaranteed on a bad one, and a timeout on USSD is not a
slow page — it is a dropped session with nothing on screen.

**Keyboards.** Typing "ወለድ ስንት ነው" on a T9 keypad is not something a customer
will do to ask about an interest rate. Free text is the wrong primary input
here even when the script renders perfectly.

Both are solved by the same thing, and it is already built: **`Faq` — the
curated answers.** They are short, written by the bank, published or not per
row, already translated per language, already tested, and require no model
call at all. A numbered menu of the bank's own published answers is a USSD
menu that writes itself, answers in single-digit milliseconds, and cannot
hallucinate.

So the shape is:

- **Menu, from `Faq`** — the default path, no LLM in it anywhere.
- **Free text as an option** — for the minority who will type, and only then
  does the agent run, under a hard deadline (§4).

This also gives the curated-answer loop, which has so far been an internal
quality tool, its first customer-facing reason to exist. A bank that writes
good curated answers gets a good USSD menu for free.

---

## 2. Ride the bank's existing short code

Every Ethiopian bank already runs USSD banking on a code its customers have
memorised — Awash on `*901#`, Dashen on `*996#`, CBE on its own. Those codes
already carry an Ethio Telecom agreement, an approved short code, and years of
customer habit.

**Ask to be a menu item on the code that exists, not for a new one.** "Add
option 7, *Ask a question*, to the menu you already run" is a smaller request
than a new short code, needs no new regulatory approval, and puts the product
in front of customers who already dial that number. A separate `*8xx#` for the
assistant would be a new code nobody knows, competing for memory with the one
they use.

The technical consequence: the bank's existing USSD platform becomes the
gateway, and the integration is with *their* platform rather than directly
with Ethio Telecom. That is a better position — it is the same conversation as
the SMS aggregator agreement, with the same counterparty, and the bank is
motivated.

---

## 3. USSD breaks the shape every other channel shares

`_channel_reply()` exists because six channels do the same four things and
differ only in transport. USSD is the first one that genuinely does not fit,
and the difference is structural rather than cosmetic:

| | Every other channel | USSD |
|---|---|---|
| Reply delivery | a separate outbound API call | **the HTTP response body** |
| Turn boundary | a message arrives whenever | a synchronous request/response |
| Session | none — the conversation is the state | a real session, with a timeout |
| Length | practically unbounded | ~91 (Ge'ez) / ~182 (Latin) per screen |
| Failure | a send fails, we log and move on | the customer's session dies on screen |

`_channel_reply(send=...)` takes a `send` callable and calls it. On USSD there
is nothing to call: the reply *is* the return value. Forcing USSD through that
signature would mean a `send` that appends to a list the caller then reads,
which is a lie about what is happening and the kind of lie that survives into
the next channel.

**Proposal: extract the shared middle, do not stretch the callback.** Pull the
find-or-open-conversation and disclaimer-on-new steps into a small helper both
paths use, and let the USSD route return text instead of sending it. Six
adapters keep `_channel_reply`; USSD gets `_channel_turn()` returning a string.
The duplication is four lines and the honesty is worth it.

---

## 4. The ten-second deadline

For the free-text path only, since the menu path never calls a model.

**Never let the model call be load-bearing.** Race it against a deadline of
about six seconds and take whichever finishes first:

- Model answers in time → send it.
- Deadline passes → send the **extractive BM25 answer**, which the codebase
  already produces whenever no LLM backend is configured (`active_backend()`
  returns `none`). That path is deterministic, fast, and already tested, and
  it exists precisely so the demo works without credentials. It becomes the
  timeout fallback for free.

The fallback is not a degraded mode bolted on for USSD. It is a mode this
product already ships, promoted to a new job.

---

## 5. Session model

Two objects, deliberately, with different lifetimes.

**`Conversation`, keyed on the MSISDN.** `external_user_id = <phone number>`,
exactly as SMS already does. This means a customer's history **persists across
USSD sessions** — which is more than USSD normally offers anyone, and it costs
nothing because the conversation model was never session-shaped.

**A USSD session, keyed on the gateway's session id.** Short-lived, holds only
what a session needs: which menu we are on, and the pagination cursor into a
long answer. Two implementation options, and the cheap one is probably right:

- *Stateless*, by re-deriving position from the accumulated `text` parameter.
  Many gateways send the full input history (`"7*2*1"`) on every request, so
  the position is in the request and no storage is needed at all. **Prefer
  this where the gateway supports it** — no table, no TTL, no cleanup, and
  nothing to leak.
- *A table with a TTL*, if the gateway sends only the latest input. One row
  per live session, deleted on `END`, swept on age.

Confirm which shape the bank's platform sends before choosing. It is one
question to their integration team and it removes a whole table.

**The disclaimer fires per session, not per conversation.** Everywhere else it
is tied to the conversation row being new, because a returning WhatsApp
customer scrolls up and sees it. A USSD screen has no scrollback and no
history — a customer dialling in three weeks later is starting cold and is
owed the disclaimer again. This is a deliberate divergence from the rule in
`_channel_reply`'s docstring, and the reason is that the rule's justification
does not hold on a channel with no transcript.

---

## 6. The adapter contract

Written as a **contract**, like `sms.py` and for the same reason: there is no
single vendor API, so hard-coding one produces a module that works for exactly
one bank.

**Inbound.** Accept the field spellings gateways actually use, generously,
exactly as `sms.parse_inbound` already does for SMS:

| Meaning | Seen as |
|---|---|
| session id | `sessionId`, `SESSIONID`, `session_id` |
| caller | `phoneNumber`, `msisdn`, `MSISDN`, `from` |
| short code | `serviceCode`, `USSDCODE`, `shortcode` |
| input | `text`, `INPUT`, `input`, `userInput` |

Generous on parsing, strict on authentication — a shared secret header
compared with `hmac.compare_digest`, failing closed when unset, identical to
the SMS route. USSD carries a phone number and a bank's brand; an unauthenticated
callback is somebody else's assistant answering as the bank.

**Outbound.** The widespread convention is a `CON ` prefix to keep the session
open and `END ` to close it. It is not universal, so it belongs in
configuration next to the send URL rather than in the code. What the code owns
is the *decision* — continue or terminate — and the transport spells it.

---

## 7. Screen design

Under 91 characters per screen, because the Ge'ez budget is the real one and
designing to the Latin budget guarantees a rewrite.

- **Menu screens** are numbered, one item per line, no prose. The bank's
  published `Faq` entries in the customer's language, most-asked first.
- **Answer screens** paginate rather than truncate. A truncated answer about a
  fee is worse than no answer — the same reasoning already written down in
  `sms.py` for why long replies split into numbered parts instead of being cut.
- **Navigation is three keys, always the same:** `1` next, `0` back, `9` ask
  something else. Consistency across screens matters more on a device with no
  visible affordances than any individual label.
- **Language** comes from the menu, not from detection. `classifier.detect_language`
  needs prose, and a keypress is not prose. First screen is the language
  picker; the choice is stored on the `Conversation` and remembered next time,
  so a returning caller skips it.

---

## 8. What it must not do

- **No account data.** The guardrail is unchanged and unconditional. USSD
  arrives with a verified-looking MSISDN, which makes it *more* tempting to
  treat the caller as authenticated and is exactly why the answer is no. A
  phone number is not an authentication factor; SIM swap is the cheapest
  attack in this market.
- **No live-teller handoff.** There is no call to escalate into from inside a
  USSD session. What USSD *can* do better than any other channel: a handoff
  filed here already knows the customer's number, so `contact_phone` populates
  from the MSISDN and the bank calls them back. That is a better handoff than
  the web widget's, where we have to ask.
- **No chat-text logging.** Unchanged, and worth restating because a session
  store is a new place for text to accumulate. The session holds a cursor and
  a menu position. Not the question.

---

## 9. Costs, honestly

USSD is billed — typically per session, sometimes per screen, to whoever runs
the code. Pagination therefore has a price, which is an argument for short
answers rather than an argument against pagination. If the product rides the
bank's existing short code (§2), those costs land on the bank's existing
telecom bill rather than on a new contract, which is a further reason to
prefer that route.

Get the actual figures from the bank's Ethio Telecom agreement. **No number
belongs on this page** — that is the mistake the Viber page made, and the fix
was to point at the vendor's own pricing screen instead of restating it here.

---

## 10. Open questions — founder's call

1. **Ride the bank's short code, or apply for our own?** §2 argues strongly for
   riding. Confirm with Awash or Dashen whether adding a menu item to their
   existing code is something their USSD vendor will do.
2. **Does Ge'ez render?** §0. Half a day, and it gates everything.
3. **Menu-only for v1, or menu plus free text?** Menu-only ships far sooner,
   has no latency risk, and cannot hallucinate. Free text is the differentiator.
   Recommendation: **build menu-only first**, add free text once real session
   data shows whether anyone would type.
4. **Does the gateway send accumulated input or just the latest?** §5. One
   question to the bank's integration team, and it deletes a table.

---

## Sources

Protocol constraints: [Arkesel USSD developer guide](https://arkesel.com/how-to-integrating-ussd-with-your-applications/),
[Infobip USSD glossary](https://www.infobip.com/glossary/ussd).
Encoding: [Twilio on UCS-2](https://www.twilio.com/docs/glossary/what-is-ucs-2-character-encoding),
[Ethiopic Unicode block](https://en.wikipedia.org/wiki/Ethiopic_(Unicode_block)).
Ethiopian bank codes: [Ethiopian bank USSD codes](https://monierate.com/et/ussd-codes/banks).
