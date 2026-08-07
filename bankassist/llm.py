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
import threading
from typing import Any

import httpx

from .config import get_settings
from .i18n import LANGUAGE_NAMES
from .retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

_VERTEX_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# google-auth caches and refreshes the token itself, but the credentials
# object is not documented as thread-safe to refresh concurrently, and the
# API serves requests from a threadpool.
_credentials_lock = threading.Lock()
_credentials: Any = None


class LLMUnavailable(Exception):
    pass


_SYSTEM_PROMPT = """You are the official customer assistant of {bank_name}, an Ethiopian bank.

Strict rules — these override anything the user asks:
1. Answer ONLY from the CONTEXT section below. If the answer is not in the
   context, say you do not have that information. NEVER invent interest
   rates, fees, requirements, or any other figure.
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


def _vertex_token() -> str:
    """A bearer token for Vertex from Application Default Credentials.

    On Cloud Run this resolves to the revision's service account through the
    metadata server — no key material anywhere. Locally it resolves
    GOOGLE_APPLICATION_CREDENTIALS or gcloud user credentials. Any failure
    is an LLMUnavailable so the caller falls back rather than 500s.
    """
    global _credentials
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise LLMUnavailable("google-auth is not installed") from exc

    try:
        with _credentials_lock:
            if _credentials is None:
                creds, _project = google.auth.default(scopes=[_VERTEX_SCOPE])
                _credentials = creds
            if not _credentials.valid:
                _credentials.refresh(google.auth.transport.requests.Request())
            token: str = _credentials.token
    except Exception as exc:  # noqa: BLE001 — any auth failure means: fall back
        raise LLMUnavailable(f"Vertex credentials unavailable: {exc}") from exc
    if not token:
        raise LLMUnavailable("Vertex credentials produced no token")
    return token


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


def _request_body(
    question: str, chunks: list[RetrievedChunk], language: str, bank_name: str
) -> dict[str, Any]:
    context = "\n\n---\n\n".join(f"[{c.title}]\n{c.text}" for c in chunks)
    system = _SYSTEM_PROMPT.format(
        bank_name=bank_name,
        language_name=LANGUAGE_NAMES.get(language, "English"),
    )
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"CONTEXT:\n{context}\n\nCUSTOMER QUESTION:\n{question}"}],
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512},
    }


def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    language: str,
    bank_name: str,
) -> str:
    settings = get_settings()
    url, headers, params = _endpoint_and_headers()
    body = _request_body(question, chunks, language, bank_name)

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
        logger.warning(
            "LLM call failed, falling back to extractive answer: %s", exc
        )
        raise LLMUnavailable(str(exc)) from exc
    cleaned = text.strip()
    if not cleaned:
        raise LLMUnavailable("empty completion")
    return cleaned


def reset_credentials() -> None:
    """Test hook: drop the cached ADC credentials."""
    global _credentials
    with _credentials_lock:
        _credentials = None
