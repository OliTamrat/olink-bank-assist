# Gemini / Vertex AI

**Status: live in production via Vertex; optional everywhere.**
Module: `bankassist/llm.py` — plain REST over httpx, **no vendor SDK**
(ADR-0004).

## The three-state backend

`active_backend()` returns `vertex | gemini | none`:

- **Vertex (production):** `GOOGLE_GENAI_USE_VERTEXAI=1` +
  `GOOGLE_CLOUD_PROJECT`. Authenticates as the Cloud Run revision's own
  service account through Application Default Credentials — **there is no API
  key anywhere**: nothing to store, leak or rotate.
- **AI Studio (dev):** `GEMINI_API_KEY`.
- **Neither:** deterministic extractive answers. The product stays demoable
  with zero credentials, and adding a model makes it conversational, not less
  safe.

## The rules the prompt enforces

Strict context-only answering: the model phrases what retrieval found and is
forbidden to add figures. The golden-question evals in CI fail any answer
carrying a number with no source. Curated (tier-1) answers never touch the
model at all — that is the point of them.

## Cost shape

Tier 1 costs zero model calls; tier 2 costs one. The channel work multiplies
inbound surface, which is why the Meta echo-loop guard matters — it is the
one bug that converts a webhook misread into an unbounded model bill (see
`integrations/meta.md`).
