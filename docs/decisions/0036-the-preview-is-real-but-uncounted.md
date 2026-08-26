# ADR-0036: The Live Preview is real traffic, and no report counts it

**Date:** 2026-08-26
**Status:** Accepted
**Supersedes:** nothing

## Context

The Dashboard's Live Preview embeds the real widget pointed at the real
assistant. That is deliberate and worth keeping — a preview that mocks its
answers tells a staff member nothing about whether their content reads well,
and the card's own caption promises the messages appear in Conversations.

Driving a **brand-new tenant** in a browser showed what nobody had looked at:
on a tenant with no knowledge base, the preview's own suggestion chips
("How do I open an account?", "What do I need for a loan?") each

- returned the honest I-don't-know reply,
- filed a `Handoff` — fake work in the escalation queue, a callback promised
  to nobody,
- asked the bank's own administrator for their name and phone number,
- and seeded **Content Gaps** with the questions that administrator had just
  tapped.

Two clicks, and the one report a bank cannot get anywhere else opened full of
the bank's own clicks. Deflection rate — the number a renewal is argued from —
moved for the same reason.

No test could have caught this. Every report was individually correct about
the rows it was handed; the rows were wrong. It is the failure this repo keeps
meeting from a new angle: **the thing measuring the work was measuring
something adjacent to it.**

A second, smaller defect surfaced in the same session: the preview iframe was
`/widget?bank=<slug>` with no `theme`, so it fell through to
`prefers-color-scheme`. On a light OS — most Ethiopian bank desktops — a white
panel rendered inside this dark one, and the colleague on a dark OS saw
something different. `?theme=` had been added to the widget for exactly this
class of problem (ADR-0030) and the one page that most obviously knows its own
theme was not passing it.

## Decision

1. **Preview conversations carry `channels.PREVIEW` and every reporting
   surface excludes them.** Analytics, operations, insights, Content Gaps and
   the escalation queue, through three shared helpers (`_not_preview`,
   `_messages_not_preview`, `_handoffs_not_preview`) rather than a literal
   repeated eleven times.
2. **They stay in Conversations.** The caption promises it, and a staff member
   who tested a wording is entitled to read the transcript back. Hiding the
   row would be a different lie.
3. **`handle_message()` is untouched.** A preview and a customer take the same
   branches, run the same guardrails, get the same reply — that is the point
   of a preview. The exclusion lives at the report, not at the write.
4. **Marking traffic uncounted is authenticated.** `POST
   /admin/api/{slug}/preview/conversation` stamps the channel and requires
   `analytics.read`; `/chat` is unchanged and simply resumes the conversation
   it is handed.
5. **The preview iframe is passed the panel's current theme**, and re-pointed
   (not re-rendered — that would discard a conversation in progress) when the
   theme is toggled.

## Why the route, and not `?preview=1` on `/chat`

A query parameter the widget could set is a parameter **anyone** can set. A
caller who can mark their own traffic preview decides what a bank's Content
Gaps and deflection rate do not show — in a banking product, that is a
data-integrity hole, not a convenience. Deciding what a report omits is a
privilege, so it is authenticated like one. The cost is one small route; the
alternative was a flag any embed URL could assert.

## Consequences

- `channels.PREVIEW` is deliberately **not** in `CATALOGUE`. It is a
  conversation origin, not a channel a bank connects, and
  `test_channel_connect_ui.py` would otherwise demand a connect form for it.
- `tests/test_preview_is_not_counted.py` walks the reporting endpoints as a
  **table**, so a report added later either excludes preview traffic or fails
  there. Same shape as `test_channel_connect_ui.py`, same reason: the failure
  mode is forgetting a site, not getting a site wrong.
- The negative direction is tested too. An exclusion that quietly swallowed
  real customers would look exactly like a working fix from inside every other
  test in that file.
- The dashboard's waiting-customer count and the queue itself already carried
  a comment saying they must filter identically. They now share one helper, so
  the next filter added to one of them cannot silently desynchronise them.
- **Still open, found in the same audit and deliberately not fixed here:** a
  fresh tenant is given no setup path (everything reads honestly empty, and
  nothing says "you have no knowledge base yet"); the conversations-per-day
  chart is the only card with no empty state; and the mobile sidebar unsticks
  rather than collapsing, so a 390px viewport scrolls past 21 nav items before
  reaching content. One concern per branch.
