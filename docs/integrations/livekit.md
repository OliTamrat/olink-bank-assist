# LiveKit — the live teller call

**Status: live; degrades cleanly when unconfigured.**
Module: `bankassist/livekit.py`.

Tier 3 of the answer model: when the assistant cannot or must not answer, the
customer is connected to a real bank teller on a live call inside the same
conversation, transcript already in front of the teller.

## The credential model

`LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`. Unset means the
Connect button simply does not render — no half-working state.

Room tokens are hand-rolled HS256 JWTs (no SDK), with `canPublishData`
**off** — the data channel is not part of the product and an enabled-but-
unused capability is attack surface.

## The boundary that matters

The teller sees the chat history and talks to the customer. The teller's
core-banking access is their own, on their own screen, under the bank's own
approvals — this product never proxies it (ADR-0001). Teller session scopes
are defined in `teller.py`; no scope at any verification level includes
money, and a module-level assert enforces it at import time.

Deep dive: `docs/video-teller.md`.
