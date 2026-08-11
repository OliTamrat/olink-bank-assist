# SMS

**Status: transport built and tested; gated on an aggregator agreement — in
Ethiopia that means Ethio Telecom or a reseller.**
Adapter: `bankassist/sms.py`. Route: `/webhooks/sms/{slug}`. Shipped in
PR #112.

## This is a contract, not a vendor integration (ADR-0014)

SMS has no single vendor API. The module defines the contract the bank's
gateway is configured against:

- **Inbound:** the aggregator POSTs form-encoded or JSON with the shared
  secret in `X-SMS-Secret`. Field names are accepted generously
  (`from`/`msisdn`/`sender`/…, `text`/`message`/`body`/…) — strict on
  authentication, generous on spelling.
- **Outbound:** POST to `sms_send_url`, `sms_auth_header` sent verbatim as
  `Authorization`, JSON body `{to, text, from}`.

**Honest limit:** an aggregator whose body shape differs still needs a
mapping written from its spec — that cannot be guessed in advance. Everything
around it (auth, conversation model, agent path, disclaimer, segmentation) is
finished.

## Connect

`POST /admin/api/{slug}/sms/connect` with the send URL (+ optional auth
header and sender id). Returns the callback URL and a **generated** inbound
secret for the aggregator.

## The money is a design input

SMS is the only channel that costs per reply, so:

- Long answers split into **numbered** parts (`(1/3)`) — parts can arrive out
  of order, and an unlabelled second half of an answer about a fee is worse
  than none. Single-part replies are never numbered.
- **Capped at `MAX_PARTS` (4), with the cut visible** — otherwise one long
  retrieval answer quietly bills the bank a dozen segments to one customer.
- A failed segment stops the rest: if part one didn't arrive, parts two and
  three are billed noise.

## Production note

`python-multipart` is a runtime dependency for this route: Starlette needs it
for `request.form()`, and its absence is an assertion at request time, not an
import error — it would have surfaced as a 500 on the first real inbound SMS.
A test caught it; the dependency is declared in `pyproject.toml` with the
reason.
