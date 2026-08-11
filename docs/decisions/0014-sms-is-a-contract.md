# ADR-0014 — SMS is a contract, not an integration

**Status:** accepted · **Date:** 2026-08-11 (PR #112)

## Context

Every other channel is one company's API. SMS goes through whichever
aggregator the bank holds an agreement with (in Ethiopia: Ethio Telecom or a
reseller). Hard-coding any one endpoint produces a module that works for
exactly one contract; guessing a vendor's body shape produces one that works
for none.

## Decision

`sms.py` defines the contract the gateway is configured against: shared
secret in `X-SMS-Secret` inbound (aggregators do not sign bodies), generous
field-name parsing, outbound as configured URL + verbatim auth header +
`{to, text, from}`. A vendor whose shape differs gets a mapping written from
its spec — stated as a limit, not discovered as a surprise.

## Consequences

- Everything around the vendor gap is finished and tested: auth,
  conversation model, disclaimer, segmentation.
- Because SMS bills per reply: numbered parts, capped at 4 with the cut
  visible, stop-on-first-failure. Cost is a design input, not an ops
  surprise.

## References

`sms.py`, `integrations/sms.md`, migration 0025.
