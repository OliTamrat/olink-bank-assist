"""LLM answer generation (Gemini via REST, no SDK — same style as the
Stripe integration in the dispatch API). If no key is configured or the call
fails, callers fall back to extractive answers; the assistant never depends
on the model being up.
"""

from __future__ import annotations

import logging

import httpx

from .config import get_settings
from .i18n import LANGUAGE_NAMES
from .retrieval import RetrievedChunk

logger = logging.getLogger(__name__)


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


def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    language: str,
    bank_name: str,
) -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMUnavailable("GEMINI_API_KEY not configured")

    context = "\n\n---\n\n".join(f"[{c.title}]\n{c.text}" for c in chunks)
    system = _SYSTEM_PROMPT.format(
        bank_name=bank_name,
        language_name=LANGUAGE_NAMES.get(language, "English"),
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"CONTEXT:\n{context}\n\nCUSTOMER QUESTION:\n{question}"}],
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512},
    }
    try:
        resp = httpx.post(
            url,
            json=body,
            params={"key": settings.gemini_api_key},
            timeout=settings.request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        text: str = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:  # noqa: BLE001 — any failure means: use the fallback
        logger.warning("Gemini call failed, falling back to extractive answer: %s", exc)
        raise LLMUnavailable(str(exc)) from exc
    cleaned = text.strip()
    if not cleaned:
        raise LLMUnavailable("empty completion")
    return cleaned
