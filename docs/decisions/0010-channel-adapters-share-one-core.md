# ADR-0010 — Channel adapters share one conversation core

**Status:** accepted · **Date:** 2026-08-11 (PR #112; pattern set by Telegram)

## Context

Seven channels. Each repeats four steps — find-or-open the conversation,
disclaimer if new, run the agent, send — and only transport differs. Copies
drift: the fourth adapter forgets the disclaimer and nothing notices.

## Decision

`_channel_reply()` in `api.py` owns the shared steps; an adapter is an
authenticated webhook that extracts `(sender, text)` plus a send function.
The disclaimer is tied to the conversation row being new, never to a
channel's "chat opened" event (Viber fires it only on fresh chats; WhatsApp
has none).

## Consequences

- A new channel is transport + credential columns + tests, not product
  logic.
- The conventions (disclaimer-first, no reply to stickers/receipts) are
  retested per channel anyway — a shared helper is exactly where a
  convention silently stops being followed.

## References

`api.py: _channel_reply()`, PR #112.
