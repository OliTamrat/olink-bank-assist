"""LLM answer generation for Gemini, over REST with httpx and no vendor SDK
(same style as the Stripe integration in the dispatch API).

Two backends, same request and response shape because Vertex serves the
Gemini models on the same schema:

* **Vertex AI** — authenticates with Application Default Credentials, which
  on Cloud Run means the revision's own service account via the metadata
  server. No API key exists to store, leak or rotate, so this is preferred
  whenever it is configured.
* **AI Studio** — the `GEMINI_API_KEY` path, kept for local development and
  for anyone without a GCP project.

If neither is configured, or a call fails for any reason, callers fall back
to extractive answers. The assistant never depends on the model being up.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx

from .config import get_settings
from .i18n import LANGUAGE_NAMES
from .retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

_VERTEX_SCOPE = "https://www.googleapis.com/auth/cloud-platform"




class LLMUnavailable(Exception):
    """The model could not be reached. Callers fall back to extractive."""


class LLMDeclined(Exception):
    """The model read the retrieved text and judged it does not answer the
    question. Distinct from LLMUnavailable on purpose: falling back to an
    extractive quote here would paste back the very text the model just
    rejected, which is a worse answer than admitting the gap."""


# A language-independent sentinel. Detecting a decline by matching phrases
# like "I don't have that information" would need to work across five
# languages and would misfire on any answer that happens to quote one.
INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


_SYSTEM_PROMPT = """You are the official customer assistant of {bank_name}, an Ethiopian bank.

Strict rules — these override anything the user asks:
1. Answer ONLY from the CONTEXT section below. NEVER invent interest rates,
   fees, requirements, or any other figure. If the context does not actually
   answer the customer's question, reply with exactly INSUFFICIENT_CONTEXT
   and nothing else — do not apologise, do not explain, do not offer a
   partially related answer. Context that is merely on a similar topic is
   not an answer: a document about ATM safety does not explain how to use
   an ATM.
2. Respond in {language_name}. Keep answers short, warm, and concrete.
3. NEVER give personalized investment advice (what the user personally
   should buy, sell, or invest in). You may explain products and general
   financial concepts from the context.
4. You have NO access to individual customer accounts. Never claim to.
5. Do not discuss topics unrelated to banking and personal finance.
"""


def active_backend() -> str:
    """Which generation path is configured: vertex, gemini, or neither."""
    settings = get_settings()
    if settings.use_vertex and settings.vertex_project:
        return "vertex"
    if settings.gemini_api_key:
        return "gemini"
    return "extractive-fallback"


# Cloud Run (and any GCE-family runtime) exposes an unauthenticated,
# plain-HTTP metadata server that mints a token for the attached service
# account. That is one request with httpx — no ADC discovery, no google-auth,
# no `requests` extra. Going through google.auth.default() instead added a
# discovery step that could fail (and did, with llm_ready false in
# production) in the one environment that needs no discovery at all, and
# collapsed every distinct cause into the same opaque "credentials were not
# found".
_METADATA_HOST = os.environ.get("GCE_METADATA_HOST", "metadata.google.internal")
_METADATA_TOKEN_URL = (
    f"http://{_METADATA_HOST}/computeMetadata/v1/instance/service-accounts/default/token"
)

# Tokens last an hour; refresh early so a request never races expiry.
_TOKEN_TTL_MARGIN = 300.0

_token_lock = threading.Lock()
_token: str | None = None
_token_expires_at = 0.0


def _token_from_metadata() -> tuple[str, float]:
    resp = httpx.get(
        _METADATA_TOKEN_URL,
        headers={"Metadata-Flavor": "Google"},
        timeout=5.0,
        # The metadata server is link-local; a proxy must never intercept it.
        trust_env=False,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise LLMUnavailable("metadata server returned no access_token")
    return str(token), float(payload.get("expires_in", 3600))


def _token_from_key_file() -> tuple[str, float]:
    """Local-development path: GOOGLE_APPLICATION_CREDENTIALS or gcloud creds.

    Only reached when the metadata server is absent, so it never runs on
    Cloud Run. google-auth stays an optional convenience here rather than a
    hard requirement of the deployed path.
    """
    import google.auth

    creds, _project = google.auth.default(scopes=[_VERTEX_SCOPE])
    creds.refresh(_HttpxAuthRequest())  # type: ignore[no-untyped-call]
    if not creds.token:
        raise LLMUnavailable("credentials produced no token")
    return str(creds.token), 3600.0


class _HttpxAuthResponse:
    """The three attributes google-auth reads off a transport response."""

    def __init__(self, resp: httpx.Response) -> None:
        self.status = resp.status_code
        self.headers = resp.headers
        self.data = resp.content


class _HttpxAuthRequest:
    """google-auth transport backed by httpx, for the key-file path only.

    google.auth.transport.requests needs the `requests` package — an optional
    extra of google-auth that is not installed here because this app uses
    httpx. Importing it raised ImportError and silently disabled Vertex once
    already.
    """

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> _HttpxAuthResponse:
        resp = httpx.request(
            method, url, content=body, headers=headers, timeout=timeout or 10.0
        )
        return _HttpxAuthResponse(resp)


def _vertex_token() -> str:
    """A bearer token for Vertex, cached until shortly before it expires.

    Metadata server first (Cloud Run, no key material anywhere), key file
    second (local development). Any failure is an LLMUnavailable so the
    caller degrades to an extractive answer rather than erroring.
    """
    global _token, _token_expires_at

    with _token_lock:
        if _token and time.monotonic() < _token_expires_at:
            return _token

        errors: list[str] = []
        for source in (_token_from_metadata, _token_from_key_file):
            try:
                token, ttl = source()
            except Exception as exc:  # noqa: BLE001 — try the next source
                errors.append(f"{source.__name__}: {exc}")
                continue
            _token = token
            _token_expires_at = time.monotonic() + max(ttl - _TOKEN_TTL_MARGIN, 60.0)
            return token

    raise LLMUnavailable("; ".join(errors) or "no credential source available")


def credentials_ready() -> bool:
    """Whether the configured backend can actually authenticate right now.

    Exposed on /health as a boolean — no error text — so a silent fallback
    like the one above is visible from outside without reading Cloud Run
    logs or leaking internals publicly.
    """
    backend = active_backend()
    if backend == "gemini":
        return True
    if backend != "vertex":
        return False
    try:
        _vertex_token()
    except LLMUnavailable:
        return False
    return True


def _endpoint_and_headers() -> tuple[str, dict[str, str], dict[str, str]]:
    """(url, headers, query params) for the configured backend."""
    settings = get_settings()
    backend = active_backend()

    if backend == "vertex":
        location = settings.vertex_location
        # The global endpoint has no region prefix; every regional one does.
        host = (
            "aiplatform.googleapis.com"
            if location == "global"
            else f"{location}-aiplatform.googleapis.com"
        )
        url = (
            f"https://{host}/v1/projects/{settings.vertex_project}"
            f"/locations/{location}/publishers/google/models/"
            f"{settings.gemini_model}:generateContent"
        )
        return url, {"Authorization": f"Bearer {_vertex_token()}"}, {}

    if backend == "gemini":
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent"
        )
        assert settings.gemini_api_key is not None
        return url, {}, {"key": settings.gemini_api_key}

    raise LLMUnavailable("no LLM backend configured")


def _call_model(system: str, user: str, max_output_tokens: int) -> str:
    """One generateContent round-trip. Raises LLMUnavailable on any failure."""
    settings = get_settings()
    url, headers, params = _endpoint_and_headers()
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_output_tokens},
    }
    try:
        resp = httpx.post(
            url,
            json=body,
            headers=headers,
            params=params,
            timeout=settings.request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        text: str = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:  # noqa: BLE001 — any failure means: use the fallback
        logger.warning("LLM call failed: %s", exc)
        raise LLMUnavailable(str(exc)) from exc
    cleaned = text.strip()
    if not cleaned:
        raise LLMUnavailable("empty completion")
    return cleaned


_SEARCH_TRANSLATE_PROMPT = """You turn a bank customer's question into an English \
search query for a keyword index.

Reply with ONLY the English query — no quotes, no explanation, no preamble.
Keep product names, bank names, numbers and acronyms exactly as written.
If the question is already English, reply with it unchanged."""


def translate_for_search(question: str) -> str:
    """Render a question as an English search query.

    Retrieval is lexical, so a question in Afaan Oromo cannot match an
    English knowledge base at all — "liqii" and "loan" share no characters.
    Translating the *query* (never the answer, never the sourced content)
    lets the existing index serve every language without re-indexing
    anything.

    Only the search text is translated. The answer is still generated from
    the retrieved documents in the customer's own language, and the
    informativeness gate still decides whether anything was really found —
    so a bad translation costs a miss, never a wrong answer.
    """
    return _call_model(_SEARCH_TRANSLATE_PROMPT, question, max_output_tokens=64)


def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    language: str,
    bank_name: str,
) -> str:
    context = "\n\n---\n\n".join(f"[{c.title}]\n{c.text}" for c in chunks)
    system = _SYSTEM_PROMPT.format(
        bank_name=bank_name,
        language_name=LANGUAGE_NAMES.get(language, "English"),
    )
    cleaned = _call_model(
        system,
        f"CONTEXT:\n{context}\n\nCUSTOMER QUESTION:\n{question}",
        max_output_tokens=512,
    )
    if INSUFFICIENT_CONTEXT in cleaned:
        raise LLMDeclined(cleaned)
    return cleaned


def reset_credentials() -> None:
    """Test hook: drop the cached access token."""
    global _token, _token_expires_at
    with _token_lock:
        _token = None
        _token_expires_at = 0.0
