# Tier 3 — ITA, the Interactive Teller Assistant

**Status:** built and live. Media path verified against real traffic (LiveKit
Cloud console, 2026-08-10: 51 WebRTC participant minutes, 100% connection
success). Sections below that read as future tense are the original
specification, kept because the reasoning still governs; where this document
and the code disagree, **the code wins** and `CLAUDE.md` records the decisions
that moved.

**Name:** ITA — Interactive Teller **Assistant**. Not ITM: an *Interactive
Teller Machine* is a physical kiosk, and being read as a hardware vendor puts
us in a procurement category we are not selling into. Not *Agent*: in Ethiopia
that means agent banking, and in 2026 it also means autonomous AI — the wrong
signal for the one feature whose point is that a human answers.

**Media layer is LiveKit, not Agora.** Agora was the original pick in this
spec; the build uses LiveKit (hand-rolled HS256 room tokens, `canPublishData`
off). Anywhere below that says Agora, read LiveKit.

**Depends on:** Fayda identity verification (performed by the teller on the
bank's own screen — we never call a Fayda API), teller staffing (the bank's),
in-country hosting (open).

---

## 1. What this is

A customer talking to a real bank teller, over video, from the chat they were
already in. Everything a person goes into a branch for **except moving money**.

It is the third tier of something that already exists, not a new product:

| Tier | What it is | Status |
|---|---|---|
| 1 | The assistant. Reads the bank's own documents. Never sees an account. | Built, live |
| 2 | Escalation. Captures the question and contact, files it, optionally pushes to the bank's helpdesk. Async. | Built, live |
| 3 | **ITA.** Real time. A bank employee, on the bank's systems, with the bank's credentials. | Built, live |

Today tier 2 ends with *"someone will get back to you."* Tier 3 ends with
*"someone is here now."* Same architecture, one real-time channel added.

### The frame that makes this sellable

The pitch is not "your chatbot is weak." Banks that already have a bot — CBE
has **Selam** on combanketh.et — have a *"Chat to live agent"* button that
today opens a text queue. Tier 3 replaces what happens after that tap. It is
additive to their existing investment and requires their security team to
grant us **nothing**.

---

## 2. What this is NOT

These are settled decisions, not defaults. Each is load-bearing.

1. **No core banking access.** Our software never holds a bank credential and
   never reads an account. The assistant's `account_blocked` refusal stays
   permanently, even after tier 3 exists.
2. **No transactions relayed on behalf of a teller.** The teller does the work
   on their own screen, in the bank's system, under the bank's audit trail. The
   moment we relay a transaction we inherit the liability and the core-banking
   integration wall comes straight back.
3. **No deposits, withdrawals or transfers.** By design, not by policy — the
   highest-risk category is out of scope entirely, which is also what makes
   the security conversation short.
4. **No outbound calls. Ever.** The customer always initiates. If people are
   trained to accept incoming video calls "from the bank", that becomes a
   fraud vector aimed at exactly the customers least able to spot it. There is
   no teller-initiated call feature and there should never be one.
5. **No media recording in v1.** See §8.

### What tier 3 does *not* change about tier 1

The video teller does not upgrade the assistant. Phase 3 — the assistant doing
authenticated account servicing itself — remains blocked on ESB integration,
INSA and NBE, exactly as before. Tier 3 routes *around* that wall for the human
path only, because the human already has the access we don't.

---

## 3. Session lifecycle

```
requested → verifying → queued → active → ended
                ↓          ↓        ↓
            unverified  abandoned  failed
```

| State | Meaning |
|---|---|
| `requested` | Customer tapped "Talk to a teller" in the chat |
| `verifying` | Fayda identity check running |
| `unverified` | Check failed or was declined — session continues at the limited scope in §5 |
| `queued` | Waiting for a teller |
| `abandoned` | Customer left before a teller joined |
| `active` | Teller joined |
| `ended` | Normal end, with a resolution note |
| `failed` | Technical failure — network, token, media |

**Verification runs before queueing, not after.** It is automated, so doing it
first means the teller opens a session with identity already settled instead
of spending the first minute on it. It also means an unverified session is
visibly marked in the queue before anyone picks it up.

**`abandoned` is a first-class state, not an error.** Queue abandonment is the
single most useful number this feature produces, and it is the number that
justifies staffing decisions. It must be recorded, not inferred.

---

## 4. What it reuses

Most of tier 3 already exists. This is the argument for building it here rather
than as a separate product.

| Need | Already built |
|---|---|
| Who the customer is, what they asked | `Conversation` + `Message`, with transcript |
| The escalation record | `Handoff` — carries `conversation_id`, `contact_name`, `contact_phone`, `status`, `resolved_by`, `resolution` |
| Staff identity and sign-in | Per-person accounts, argon2id, revocable server-side sessions |
| Who may do what | Permissions in code, roles as per-bank data |
| Every action recorded | `audit_log` with actor, action, entity, metadata |
| Tenant isolation | Every query filters by `bank_id`; there is a test that enforces it |
| Staff already read transcripts | `/conversations/{id}/messages` and the Conversations page |
| Five languages | `strings.json` + the language classifier |

**New objects needed:** a `TellerSession` (the real-time state above, linked to
a conversation and a handoff), a verification record, and Agora token minting.
Two new permissions: `teller.serve` (join and conduct a session) and
`sessions.read` (see the history without being able to join).

`teller.serve` goes to a **new built-in role**, not to `operator`. Working a
queue asynchronously and representing the bank live to a customer are different
jobs with different training, and the role split should say so.

---

## 5. Identity, and what it gates

Fayda verification produces three scopes. This is the core of the design.

| Scope | What the teller may do |
|---|---|
| **Unverified** | General product explanation, guidance, "which account suits me". Everything tier 1 does, with a person. Nothing specific to this customer. |
| **Verified** | Anything about *this* customer: their application, their documents, their dispute, their card request, walking them through a form. |
| **Never — at any scope** | Move money. Deposits, withdrawals, transfers. |

**Identity state is visible to both sides for the entire session.** This is the
element no consumer video app has, and it is the most important thing on either
screen — it is what tells the teller what they are allowed to do, and it tells
the customer why they are being asked for more.

CBE already runs a Fayda portal at `cbefayda.cbe.com.et`, so the identity rail
and the institutional buy-in for it exist. That is a materially easier
conversation than introducing Fayda to a bank.

---

## 6. The two screens

Visual direction: dark surface, large thumb-reachable controls, full-bleed
remote video with picture-in-picture self view.

### Customer

- **Before connecting:** who they will speak to, what that teller can and
  cannot help with, and — if the bank enables recording — that notice. Stating
  the boundary *before* the queue is the difference between a good experience
  and someone waiting ten minutes to be refused live.
- **In session:** mute, camera toggle, end, **share screen**, and attach a
  document. Share-screen is the most valuable control here and consumer apps
  treat it as secondary — a teller walking someone through a form, or a
  customer holding up a document, is most of what a non-cash session *is*.
- **Teller's name and employee ID**, visible and verifiable.

### Teller

- **A queue, not a contact list.** A customer does not choose their teller.
  The queue sorts by waiting time and shows: verified or not, language, what
  the assistant already tried, and the transcript.
- **The transcript, on connect.** Settled: the teller does not start cold.
  Bank staff already read transcripts through the Conversations page, so this
  is the same class of access, not a new exposure.
- **A resolution note at the end**, written back to the `Handoff` — which
  already has `resolution` and `resolved_by`.

### On duty is declared, not inferred

**Presence is a switch a teller throws, not a page they keep open.**

The first implementation inferred it: whoever had the Live queue page open was
present, because that page was already polling and the signal was free. It
shipped and failed in the field, in both directions at once. A teller working
anywhere else in the console — Escalations, Conversations, the knowledge base
— silently took the bank off the air, so the tenant was switched on, staffed,
and still showed no Connect button to anybody. And a teller who wanted to stop
taking calls could not, because the page they were on kept putting them back.

What made it hard to diagnose is that nothing was broken. Every part behaved
as written; the design had made a product-level fact — "customers can talk to
a person" — into a fact about a browser tab.

So: an explicit **On duty** toggle in the sidebar, on every page, with a
heartbeat behind it (`POST /teller/presence`, every 30s against a 90s
staleness window, so two dropped beats are survivable). Signing out clears it,
because that is the one moment we know for certain the person has left.
Nothing else writes presence — reading the queue emphatically does not.

The corollary is on the customer's side: **what the assistant says has to
follow from whether anyone is actually on duty.** With a banker available it
names the button; with nobody available it says plainly that no one is free
right now and asks how to reach them instead. The version that said "I have
passed you to our customer service team" either way is what produced the
complaint that started all of this — an acknowledgement, a captured phone
number, and no button anywhere on screen.

---

## 7. Degradation is a designed mode, not an error

**Audio first. Video is an upgrade the customer opts into.**

Outside Addis, audio-only will be the common case, not the exception. A session
that requires video is a different and much smaller product than one that works
at 3G. Screen-share plus voice covers most of what a teller session needs and
costs a fraction of the bandwidth.

Agora bills per minute and Ethiopian mobile data is expensive for the customer
too — so the cheap path must be the default path, not the fallback.

---

## 8. Data, recording, and residency

**Recommendation: do not record media in v1.**

The audit trail is who joined, when, for how long, what was verified, and what
was concluded — not a video file. That is enough for a dispute and enough for
an auditor, and it sidesteps the heaviest question in the whole design.

Recording video of customers means storing biometric-adjacent personal data
under Art. 22, which makes in-country hosting unambiguously mandatory rather
than merely overdue. If a bank insists on recording, that is a per-bank setting
gated on their own legal position — and it must be disclosed to the customer
before the call starts, visibly, not buried.

**Already true and worth fixing regardless:** the customer is told a human will
see their chat only *at the point of escalation* ("I've noted your question for
our customer service team"). A customer who chats and never escalates is never
told the conversation is stored and readable by bank staff. That is an Art. 22
transparency gap in the product **today**, it is about one line in the widget,
and it gets sharper with video because a live human joins mid-conversation.

---

## 9. Security invariants

To be enforced in code and never regressed. Same register as the existing
gotchas list.

1. **Agora tokens are minted server-side**, short-lived, scoped to one channel
   and one session, with an explicit role. The App Certificate never reaches a
   client. This is the standard footgun in every Agora integration.
2. **Channel names are unguessable and non-enumerable.** A predictable channel
   name is a way to join someone else's banking call.
3. **Joining is permission-checked and audited**, with the teller's identity.
   `teller.serve` is required, checked server-side on every join.
4. **Tenant isolation holds.** A teller at one bank can never be routed a
   session from another.
5. **Sessions expire.** An abandoned `active` session must not hold an open
   channel indefinitely.
6. **The customer initiates. Always.** No API path exists that creates a
   session addressed at a customer.
7. **A live camera always has an off switch on screen.** Found on a real call
   (2026-08-15): on an *audio* session the customer pressed "Show my ID", the
   camera came on — the teller's dashboard showed the video — and no control
   anywhere turned it off, because every camera control was keyed on the media
   the customer had CHOSEN rather than on what the camera was doing. The
   customer's own screen meanwhile read "your camera is not available", since
   `setCameraEnabled(true)` had rejected after the track was already
   published, and the code took that rejection as proof the camera was off.
   A camera pointed at somebody's home is not a state this product may enter
   without an exit, and "the session type says this cannot be happening" is
   exactly the reasoning that produced it. `tests/test_call_camera_controls.py`.

---

## 10. Scope

### v1 — buildable with no core banking integration

Customer taps from chat → Fayda verification → queue → teller joins →
audio (video optional) + screen share + document upload → teller writes a
resolution note → session ends → transcript and note attached to the handoff.

Everything in §5 "unverified" and "verified" that does not move money. The
teller uses their own core banking terminal for anything requiring it; our
software does not see it.

### Later

- Recording, if a bank's legal position requires it
- Appointment booking rather than live queueing
- Teller-side templates and knowledge lookup during a call

### Never

Money movement, outbound calls, core banking credentials in our system.

---

## 11. Blocked on whom

| Item | Owner |
|---|---|
| Fayda verification API access for the bank | **Bank** |
| NBE position on remote KYC for account opening | **Bank / counsel** |
| Agora account, App ID + Certificate | **Us** |
| Teller staffing and hours | **Bank** — they staff it, we sell the software. If we staff it we are a BPO, which is a different business with different economics. |
| In-country hosting | **Us + bank** — already overdue for chat logs; mandatory before any recording |
| The number that sells this: what happens today after someone taps CBE's "Chat to live agent" — wait time, abandonment, resolution rate | **Bank.** If they do not measure it, that is the opening. If they do and it is bad, that is the pitch. |
