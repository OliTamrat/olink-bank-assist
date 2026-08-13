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

import json
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
2. When the customer asks how to DO or FIX something, give them the steps.
   If the context contains a workaround, an alternative channel or a
   self-service option, SAY IT — that is the answer. A phone number, an
   email address or "visit a branch" is a LAST resort, offered after the
   steps, never instead of them.
   If the ONLY relevant thing the context offers is a contact detail or a
   referral, you have not answered the question: reply with exactly
   INSUFFICIENT_CONTEXT. Telling a customer whose app has stopped working
   to send an email is not help; it is the assistant giving up while
   appearing to answer.
3. Respond in {language_name}. Keep answers short, warm, and concrete —
   short never means dropping a step the customer needs. Prefer the
   complete short answer over the shortest one.
   COMPOSE in {language_name} rather than translating an English sentence
   into it: everyday spoken register, short sentences, common words over
   literary ones. A customer must not be able to tell the reply began life
   in another language. Leave proper nouns as they are — the bank's name,
   Telegram, WhatsApp, Fayda.
4. NEVER give personalized investment advice (what the user personally
   should buy, sell, or invest in). You may explain products and general
   financial concepts from the context.
5. You have NO access to individual customer accounts. Never claim to.
6. Do not discuss topics unrelated to banking and personal finance.
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


def _extract_text(data: dict[str, Any]) -> str:
    """Pull the answer out of a generateContent response, or say why there isn't one.

    Indexing straight into candidates[0].content.parts[0].text raises a bare
    KeyError the moment the model returns a candidate with no parts, and the
    caller then logs "LLM call failed: 'parts'" — which names nothing. The
    single most common cause is finishReason=MAX_TOKENS, so surface it: that
    one word is the difference between a five-minute fix and a silent feature.

    Thought parts are skipped. A thinking model can return its reasoning
    alongside the answer, and pasting that to a bank customer would be worse
    than returning nothing.
    """
    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMUnavailable(f"no candidates (promptFeedback={data.get('promptFeedback')!r})")
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(
        part["text"]
        for part in parts
        if isinstance(part, dict) and "text" in part and not part.get("thought")
    ).strip()
    if not text:
        raise LLMUnavailable(
            f"no text in completion (finishReason={candidate.get('finishReason')!r})"
        )
    return text


def _call_model(system: str, user: str, max_output_tokens: int, *, thinking_budget: int) -> str:
    """One generateContent round-trip. Raises LLMUnavailable on any failure.

    thinking_budget is deliberately required rather than defaulted. On Gemini
    2.5 models maxOutputTokens caps thinking *and* answer together, and
    thinking is on by default — so a caller that sizes the cap for the answer
    alone can have the whole budget consumed before a single output token is
    produced, and get back a candidate with no text. That is not a loud
    failure: it degrades to the extractive path, which looks like "the model
    had nothing to say" rather than "the call never really ran". Making every
    call site state its budget is what keeps that from being an accident.
    """
    settings = get_settings()
    url, headers, params = _endpoint_and_headers()
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_output_tokens,
            # Explicit, never inherited. The default is the model's to change.
            "thinkingConfig": {"thinkingBudget": thinking_budget},
        },
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
        data: dict[str, Any] = resp.json()
    except Exception as exc:  # noqa: BLE001 — any failure means: use the fallback
        logger.warning("LLM call failed: %s", exc)
        raise LLMUnavailable(str(exc)) from exc
    try:
        return _extract_text(data)
    except LLMUnavailable as exc:
        logger.warning("LLM call returned no usable text: %s", exc)
        raise


_SEARCH_TRANSLATE_PROMPT = """You turn a bank customer's question into an English \
search query for a keyword index.

Reply with ONLY the English query — no quotes, no explanation, no preamble.
Keep product names, bank names, numbers and acronyms exactly as written.
If the question is already English, reply with it unchanged."""


_GENERAL_PROMPT = """You are the customer assistant of {bank_name}, an Ethiopian \
bank. {bank_name}'s own knowledge base has NOTHING covering this question.

You may answer ONLY if the question is about universally-standard banking
procedure or general financial education — the kind of thing that is identical
at every bank and every ATM in the world. Examples of what you MAY explain: how
to physically use an ATM, what a PIN is and why to keep it secret, what a
savings account is, how interest compounds, general online-banking safety,
and **first-line troubleshooting for a banking app that has stopped working**
— check the connection, close and reopen it, install the pending update,
restart the phone, confirm the phone number on the account has not changed.
Those steps are the same on every banking app ever written, and a customer
locked out of theirs needs them more than they need an email address.

Reply with exactly INSUFFICIENT_CONTEXT and nothing else if answering would
require ANY of the following, because these vary by bank and country and you do
NOT know {bank_name}'s:
- any fee, charge, commission, exchange rate or interest rate
- any limit (daily withdrawal, transfer ceiling, minimum balance)
- eligibility, required documents, or how to apply for anything
- product names, branch locations, phone numbers, opening hours
- which card networks, partners or channels are supported
- anything at all specific to {bank_name}

Never state or imply a number. Never say what {bank_name} offers, allows,
charges or requires — you do not know. If the customer needs any of that, say
they should check with {bank_name} directly.

Respond in {language_name}. Be brief and practical."""


def answer_from_general_knowledge(question: str, language: str, bank_name: str) -> str:
    """Answer a universally-standard banking question with no bank content.

    A deliberate, bounded exception to tool-output-is-truth. ATM mechanics are
    the same on every NCR and Diebold machine on earth, and an assistant that
    cannot explain what a PIN is looks broken on exactly the questions a
    first-time customer asks.

    The boundary is the whole design. The failure mode is not "explains how to
    use an ATM" — it is helpfully appending "you can usually withdraw up to
    5,000 birr a day", inventing a policy for a bank it knows nothing about.
    So the model may explain procedure and concepts, and must decline the
    moment an answer would need a figure, a limit, a requirement, or anything
    specific to this bank. Raises LLMDeclined when it refuses.
    """
    system = _GENERAL_PROMPT.format(
        bank_name=bank_name,
        language_name=LANGUAGE_NAMES.get(language, "English"),
    )
    # Thinking on, and the cap covers thinking + answer. The decline checklist
    # in _GENERAL_PROMPT is the safety property here — the model has to weigh
    # "would answering this need a figure or a limit?" — so this is exactly
    # the call that should reason before replying.
    cleaned = _call_model(system, question, max_output_tokens=1200, thinking_budget=512)
    if INSUFFICIENT_CONTEXT in cleaned:
        raise LLMDeclined(cleaned)
    return cleaned


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
    # Thinking off: this is a mechanical transformation, not a judgement, and
    # it sits on the miss path where latency is already worst. The 64-token
    # cap this replaces was the bug — with thinking on by default, the budget
    # was spent before any query came out, translate_for_search raised
    # LLMUnavailable on every call, agent.py swallowed it into english="",
    # and cross-language retrieval never ran in production at all.
    return _call_model(
        _SEARCH_TRANSLATE_PROMPT, question, max_output_tokens=256, thinking_budget=0
    )


# A sentinel rather than an empty string, for the same reason
# INSUFFICIENT_CONTEXT is one: "the message was already clear" and "the model
# produced nothing" are different outcomes, and an empty reply cannot tell
# them apart.
NOTHING_TO_REFINE = "ALREADY_CLEAR"

_REFINE_PROMPT = """You turn a bank customer's message into a search query for \
that bank's own help documents.

The customer may not write well. Expect misspellings, missing words, no \
punctuation, words in the wrong order, and two- or three-word fragments. Many \
customers are new to written banking and some are typing in their second \
language. That is normal and is not a reason to give up.

Your job is ONLY to work out what they are looking for and write it as a clear, \
short query. Rules:

1. Reply with the query and nothing else. No explanation, no quotes.
2. Write the query in the SAME language the customer used.
3. Fix spelling. Expand fragments into a full request: "how open acount" is \
"how do I open an account".
4. Keep it faithful. Use only what they said and the ordinary banking meaning \
of it. NEVER add a product name, a figure, a limit or a condition they did not \
mention — you are rewriting their question, not answering it.
5. If the message is already a clear question, or if you genuinely cannot tell \
what they want, reply with exactly ALREADY_CLEAR and nothing else. Guessing \
wrongly sends them a confidently irrelevant answer, which is worse than asking \
them what they meant."""


def refine_for_search(message: str) -> str:
    """Rewrite a badly-typed message as a clear search query, same language.

    The literacy path. Lexical retrieval is unforgiving of how a question is
    written, and the failure is not the one you would expect: it is rarely
    silence. Measured against the seeded CBE corpus, "how open acount"
    retrieves **Transfers to Telebirr** — the typo kills `acount`, leaving
    `open`, which matches "open" in an unrelated document. Retrieval succeeds
    confidently on the wrong thing, the model then reads it and correctly
    declines, and the customer is escalated to a teller.

    So this runs on the *failure* path — no chunks, or the model declined —
    and never on the common case, which pays nothing for it.

    Same doctrine as `translate_for_search`, and it is what makes this safe:
    **only the search text is rewritten.** The answer is still generated from
    whatever documents come back, the informativeness gate still decides
    whether anything was really found, and the model may still decline. A bad
    rewrite therefore costs a miss, never a wrong answer.

    Raises LLMUnavailable with no backend configured — the caller skips the
    retry and the clarifying question takes over, so extractive mode keeps
    working.
    """
    # Thinking off, like translate_for_search: this is a rewrite, not a
    # judgement, and it sits on the path where latency is already worst. The
    # one judgement it makes — "can I tell what they meant?" — is a single
    # bit answered by ALREADY_CLEAR, not something worth a thinking budget.
    return _call_model(
        _REFINE_PROMPT, message, max_output_tokens=256, thinking_budget=0
    )


_CURATED_TRANSLATE_PROMPT = """You translate a bank's own approved customer \
answer into {language_name}, for {bank_name}, an Ethiopian bank.

This text will be shown to a customer as the bank's own words, so translate it
faithfully and completely. Do NOT summarise, improve, shorten or add anything.

Keep EXACTLY as written, untranslated: product and brand names, bank names,
every number, currency amount, percentage, date, phone number, email address,
account and code (for example Amole, Sharik, Zoorya, ETB 5,000, 6333, ISO
20022, 22 November 2025).

Preserve the line breaks and any bullet or list structure.

Reply with ONLY the translated text — no quotes, no explanation, no preamble."""


def translate_curated(text: str, language: str, language_name: str,
                      bank_name: str) -> str:
    """Render an approved answer in another language, word for word.

    Unlike `translate_for_search`, this output is read by a customer, so the
    prompt forbids summarising and pins every figure and product name. That is
    a mitigation, not a guarantee — which is why what comes back is stored as
    a DRAFT and goes to a native speaker before it is ever served. The model
    gets the wording started; a person is still what makes it the bank's word.

    Thinking off: this is a mechanical transformation like the search
    translation, and a thinking budget on a 160-answer batch is paid 640 times
    for no gain.
    """
    prompt = _CURATED_TRANSLATE_PROMPT.format(
        language_name=language_name, bank_name=bank_name
    )
    return _call_model(prompt, text, max_output_tokens=2048, thinking_budget=0)


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
    # Same reasoning as the general path: deciding INSUFFICIENT_CONTEXT is a
    # judgement about whether the retrieved text answers the question, and the
    # 512 cap had to cover thinking as well as a multi-sentence answer.
    cleaned = _call_model(
        system,
        f"CONTEXT:\n{context}\n\nCUSTOMER QUESTION:\n{question}",
        max_output_tokens=1500,
        thinking_budget=512,
    )
    if INSUFFICIENT_CONTEXT in cleaned:
        raise LLMDeclined(cleaned)
    return cleaned


_INSIGHTS_PROMPT = """You are the analytics engine behind the operations \
console of {bank_name}, a bank whose AI customer assistant and live-teller \
queue produced the aggregate metrics you are given as JSON.

Analyze the data yourself: look for patterns, contrasts and trade-offs
across volumes, deflection, escalation desks, the live-call funnel, staffing
and hourly load. The `machine_findings` entries are hints from simple
threshold rules — you may confirm, reprioritise or go beyond them, but do
not merely restate them.

Reply with ONLY a JSON object, no code fences and no other text, in exactly
this shape:

{{"headline": "one sentence, the single most important thing",
 "assessment": [{{"title": "short heading", "body": "a short paragraph"}}],
 "actions": [{{"text": "one concrete, modest step", "priority": "now"}}]}}

Rules, all of them hard:
- Every string is written in {language_name}. COMPOSE in that language — do
  not write an English sentence and render it word by word. Use the everyday
  register a branch manager would use in conversation, short sentences, and
  common vocabulary in preference to literary or academic words. A sentence
  that is grammatical but reads as translated has failed this rule.
- Leave proper nouns alone: the bank's name, channel names (Telegram,
  WhatsApp) and Fayda are written as they are.
- 2 to 4 assessment sections; 2 to 4 actions; "priority" is exactly one of
  "now", "soon" or "later".
- Use ONLY numbers present in the data. Never invent, estimate, extrapolate
  or combine numbers into new figures. If something is null, it was not
  measured — do not guess it.
- The data contains no customer messages, so never quote or imagine any."""


def _parse_brief(raw: str) -> dict[str, Any]:
    """The model's JSON, validated into the shape the page renders.

    Anything malformed raises LLMUnavailable rather than rendering broken —
    the caller falls back to the deterministic findings, which is a better
    page than a half-parsed brief.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise LLMUnavailable(f"brief was not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMUnavailable("brief was not an object")
    headline = data.get("headline")
    assessment = data.get("assessment")
    actions = data.get("actions")
    if not isinstance(headline, str) or not headline.strip():
        raise LLMUnavailable("brief has no headline")
    if not isinstance(assessment, list) or not assessment:
        raise LLMUnavailable("brief has no assessment")
    clean_sections = []
    for section in assessment[:6]:
        if (
            isinstance(section, dict)
            and isinstance(section.get("title"), str)
            and isinstance(section.get("body"), str)
        ):
            clean_sections.append(
                {"title": section["title"].strip(), "body": section["body"].strip()}
            )
    if not clean_sections:
        raise LLMUnavailable("brief sections were malformed")
    clean_actions = []
    if isinstance(actions, list):
        for action in actions[:6]:
            if isinstance(action, dict) and isinstance(action.get("text"), str):
                priority = action.get("priority")
                clean_actions.append({
                    "text": action["text"].strip(),
                    # An unknown priority degrades to the middle, never to a
                    # rendering error.
                    "priority": priority if priority in ("now", "soon", "later") else "soon",
                })
    return {
        "headline": headline.strip(),
        "assessment": clean_sections,
        "actions": clean_actions,
    }


def analyze_operations(digest: str, language: str, bank_name: str) -> dict[str, Any]:
    """A structured operations brief the model composed itself.

    The model is the analyst here, not a copywriter over precomputed
    findings — it receives the full aggregate picture and decides what
    matters. The digest is built by the caller from the analytics payloads
    with the customer-text fields excluded, so the model physically cannot
    quote a customer — the safety is what it is *given*, with the prompt as
    the second fence rather than the first.

    Raises LLMUnavailable like every other call (including on malformed
    output); the caller degrades to the deterministic findings.
    """
    system = _INSIGHTS_PROMPT.format(
        bank_name=bank_name,
        language_name=LANGUAGE_NAMES.get(language, "English"),
    )
    # Thinking on and sized generously: this is the one call in the product
    # whose entire job is judgement over a whole dataset, and the cap covers
    # thinking + a multi-section brief.
    raw = _call_model(system, digest, max_output_tokens=2400, thinking_budget=768)
    return _parse_brief(raw)


def reset_credentials() -> None:
    """Test hook: drop the cached access token."""
    global _token, _token_expires_at
    with _token_lock:
        _token = None
        _token_expires_at = 0.0
