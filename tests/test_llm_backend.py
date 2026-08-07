"""Backend selection and request shape for Gemini generation.

Vertex is unreachable from CI and from the sandbox, so these assert what can
be asserted offline: which backend gets chosen, that the Vertex request is
addressed and authenticated correctly, and — most importantly — that every
failure path still degrades to the extractive answer rather than surfacing
an error to a bank's customer.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from bankassist import config, llm
from bankassist.retrieval import RetrievedChunk

CHUNK = RetrievedChunk(
    chunk_id="c1",
    document_id="d1",
    title="Opening an Account",
    text="Bring a valid ID and a minimum deposit.",
    score=1.0,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "GEMINI_API_KEY",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "VERTEX_LOCATION",
    ):
        monkeypatch.delenv(var, raising=False)
    config.reset_settings()
    llm.reset_credentials()


def test_no_configuration_means_extractive(monkeypatch: pytest.MonkeyPatch) -> None:
    assert llm.active_backend() == "extractive-fallback"
    with pytest.raises(llm.LLMUnavailable):
        llm.generate_answer("q", [CHUNK], "en", "Demo Bank")


def test_api_key_alone_selects_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    config.reset_settings()
    assert llm.active_backend() == "gemini"


def test_vertex_wins_when_both_are_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    # No key to leak beats a key, so Vertex takes precedence.
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "olink-bank-assist")
    config.reset_settings()
    assert llm.active_backend() == "vertex"


def test_vertex_flag_without_a_project_is_not_vertex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A half-configured deployment must not claim a backend it can't reach.
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "1")
    config.reset_settings()
    assert llm.active_backend() == "extractive-fallback"


def _use_vertex_env(monkeypatch: pytest.MonkeyPatch, location: str = "us-central1") -> None:
    """Configure Vertex without stubbing the token, so the auth path runs."""
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "olink-bank-assist")
    monkeypatch.setenv("VERTEX_LOCATION", location)
    config.reset_settings()


def _use_vertex(monkeypatch: pytest.MonkeyPatch, location: str = "us-central1") -> None:
    _use_vertex_env(monkeypatch, location)
    monkeypatch.setattr(llm, "_vertex_token", lambda: "fake-token")


def test_vertex_request_is_addressed_and_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex(monkeypatch)
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        seen["params"] = kwargs.get("params")
        seen["json"] = kwargs.get("json")
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Bring a valid ID."}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    answer = llm.generate_answer("How do I open an account?", [CHUNK], "en", "Demo Bank")

    assert answer == "Bring a valid ID."
    assert seen["url"] == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/olink-bank-assist"
        "/locations/us-central1/publishers/google/models/"
        "gemini-2.5-flash:generateContent"
    )
    assert seen["headers"]["Authorization"] == "Bearer fake-token"
    # The API key must never ride along on the Vertex path.
    assert not seen["params"]
    # The safety prompt has to reach the model, not just live in the source.
    system = seen["json"]["systemInstruction"]["parts"][0]["text"]
    assert "Answer ONLY from the CONTEXT" in system
    assert "NO access to individual customer accounts" in system


def test_global_location_drops_the_region_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex(monkeypatch, location="global")
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen["url"] = url
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    llm.generate_answer("q", [CHUNK], "en", "Demo Bank")
    assert seen["url"].startswith("https://aiplatform.googleapis.com/v1/projects/")
    assert "/locations/global/" in seen["url"]


def test_auth_failure_degrades_instead_of_erroring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The failure mode that matters: a missing or expired credential must
    # produce an extractive answer, never a 500 to a bank's customer.
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "olink-bank-assist")
    config.reset_settings()

    def broken_token() -> str:
        raise llm.LLMUnavailable("no credentials here")

    monkeypatch.setattr(llm, "_vertex_token", broken_token)
    with pytest.raises(llm.LLMUnavailable):
        llm.generate_answer("q", [CHUNK], "en", "Demo Bank")


def test_http_error_degrades_instead_of_erroring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex(monkeypatch)

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(429, json={"error": "quota"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(llm.LLMUnavailable):
        llm.generate_answer("q", [CHUNK], "en", "Demo Bank")


def test_empty_completion_is_treated_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex(monkeypatch)

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "   "}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(llm.LLMUnavailable):
        llm.generate_answer("q", [CHUNK], "en", "Demo Bank")


def test_health_reports_the_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from bankassist.api import app

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "olink-bank-assist")
    config.reset_settings()
    with TestClient(app) as client:
        assert client.get("/health").json()["llm"] == "vertex"


def test_vertex_token_uses_a_transport_that_actually_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression that shipped: google.auth.transport.requests needs the
    `requests` package, an optional extra we don't install because we use
    httpx. Importing it raised ImportError, generate_answer() fell back, and
    Vertex silently never ran despite being configured correctly.

    The earlier tests all mocked _vertex_token, so none of them touched this
    path. This one drives the real function with a fake credential, so the
    transport must genuinely import and be callable.
    """
    _use_vertex_env(monkeypatch)

    refreshed: dict[str, Any] = {}

    class FakeCreds:
        valid = False
        token = "minted-token"

        def refresh(self, request: Any) -> None:
            # google-auth calls the transport; it must be usable, not just
            # constructible.
            refreshed["transport"] = type(request).__name__
            self.valid = True

    import google.auth

    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (FakeCreds(), "proj"))
    llm.reset_credentials()

    assert llm._vertex_token() == "minted-token"
    assert refreshed["transport"] == "_HttpxAuthRequest"


def test_credentials_ready_is_false_when_auth_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex_env(monkeypatch)

    def broken() -> str:
        raise llm.LLMUnavailable("nope")

    monkeypatch.setattr(llm, "_vertex_token", broken)
    assert llm.credentials_ready() is False


def test_credentials_ready_is_true_when_a_token_mints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex_env(monkeypatch)
    monkeypatch.setattr(llm, "_vertex_token", lambda: "tok")
    assert llm.credentials_ready() is True


def test_health_exposes_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from bankassist.api import app

    _use_vertex_env(monkeypatch)
    monkeypatch.setattr(llm, "_vertex_token", lambda: "tok")
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["llm"] == "vertex"
    assert body["llm_ready"] is True


def test_health_is_never_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    # /health answers "what is running right now". A cached copy answers it
    # wrong with full confidence — hit once mid-deploy it keeps reporting the
    # previous build's fields, which is exactly how a successful deploy got
    # mistaken for a failed one.
    from fastapi.testclient import TestClient

    from bankassist.api import app

    with TestClient(app) as client:
        resp = client.get("/health")
    assert "no-store" in resp.headers.get("cache-control", "")

def test_token_comes_from_the_metadata_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloud Run's own path: one plain HTTP call, no ADC discovery.

    Going through google.auth.default() instead added a discovery step that
    failed in the one environment needing no discovery, and reported every
    distinct cause as the same opaque "credentials were not found".
    """
    _use_vertex_env(monkeypatch)
    llm.reset_credentials()
    seen: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        seen["trust_env"] = kwargs.get("trust_env")
        return httpx.Response(
            200,
            json={"access_token": "metadata-token", "expires_in": 3599},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    assert llm._vertex_token() == "metadata-token"
    assert seen["url"].endswith("/instance/service-accounts/default/token")
    assert seen["headers"]["Metadata-Flavor"] == "Google"
    # The metadata server is link-local — a proxy must never intercept it.
    assert seen["trust_env"] is False


def test_the_token_is_cached_between_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vertex_env(monkeypatch)
    llm.reset_credentials()
    calls = {"n": 0}

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={"access_token": "tok", "expires_in": 3599},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    assert llm._vertex_token() == "tok"
    assert llm._vertex_token() == "tok"
    assert calls["n"] == 1, "a cached token must not be re-minted every request"


def test_a_dead_metadata_server_does_not_wedge_the_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex_env(monkeypatch)
    llm.reset_credentials()

    def dead_get(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("no metadata server here")

    def dead_key_file() -> tuple[str, float]:
        raise RuntimeError("no ADC either")

    monkeypatch.setattr(httpx, "get", dead_get)
    monkeypatch.setattr(llm, "_token_from_key_file", dead_key_file)

    with pytest.raises(llm.LLMUnavailable):
        llm._vertex_token()
    assert llm.credentials_ready() is False


def test_key_file_is_the_fallback_when_metadata_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Local development has no metadata server; it must still work.
    _use_vertex_env(monkeypatch)
    llm.reset_credentials()

    def dead_get(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("not on GCE")

    monkeypatch.setattr(httpx, "get", dead_get)
    monkeypatch.setattr(llm, "_token_from_key_file", lambda: ("key-file-token", 3600.0))
    assert llm._vertex_token() == "key-file-token"


# ------------------------------------------------------- thinking budgets
#
# The regression these lock in: on Gemini 2.5 models maxOutputTokens caps
# thinking AND answer together, and thinking is on unless you say otherwise.
# translate_for_search asked for 64 tokens, the budget went entirely to
# thinking, the response came back with a candidate carrying no parts, the
# old indexing raised KeyError('parts'), _call_model turned that into
# LLMUnavailable, and agent.py swallowed it into english="" — so
# cross-language retrieval was dead in production while every test passed,
# because every test monkeypatched translate_for_search itself.


def _capture(monkeypatch: pytest.MonkeyPatch, text: str = "loan information") -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen["json"] = kwargs.get("json")
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    return seen


def test_translation_disables_thinking_and_leaves_room_for_a_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex(monkeypatch)
    seen = _capture(monkeypatch)

    assert llm.translate_for_search("waa'ee liqii barbaada") == "loan information"

    cfg = seen["json"]["generationConfig"]
    assert cfg["thinkingConfig"]["thinkingBudget"] == 0
    assert cfg["maxOutputTokens"] >= 256


def test_answer_paths_budget_for_thinking_on_top_of_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both judgement calls must leave room for the answer after thinking.

    generate_answer and answer_from_general_knowledge each have to decide
    whether to decline before writing anything. If the cap only covers the
    prose, the decline reasoning eats it and the caller sees an empty
    completion — which degrades to extractive and looks like the model simply
    had nothing useful to say.
    """
    for call in (
        lambda: llm.generate_answer("q", [CHUNK], "en", "Demo Bank"),
        lambda: llm.answer_from_general_knowledge("How do I use an ATM?", "en", "Demo Bank"),
    ):
        _use_vertex(monkeypatch)
        seen = _capture(monkeypatch, text="Insert your card and enter your PIN.")
        call()
        cfg = seen["json"]["generationConfig"]
        budget = cfg["thinkingConfig"]["thinkingBudget"]
        assert budget > 0
        assert cfg["maxOutputTokens"] - budget >= 512


def test_a_candidate_with_no_parts_names_the_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact production shape of the bug, and the diagnosis it now gives.

    Previously this raised KeyError('parts') and was logged as
    "LLM call failed: 'parts'", which names nothing at all.
    """
    _use_vertex(monkeypatch)

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"finishReason": "MAX_TOKENS", "content": {"role": "model"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(llm.LLMUnavailable, match="MAX_TOKENS"):
        llm.translate_for_search("waa'ee liqii barbaada")


def test_thought_parts_are_never_shown_to_a_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex(monkeypatch)

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "The user is asking about loans...", "thought": True},
                                {"text": "Bring a valid ID."},
                            ]
                        }
                    }
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    assert llm.generate_answer("q", [CHUNK], "en", "Demo Bank") == "Bring a valid ID."


def test_a_blocked_prompt_degrades_instead_of_erroring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vertex(monkeypatch)

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={"promptFeedback": {"blockReason": "SAFETY"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(llm.LLMUnavailable, match="no candidates"):
        llm.generate_answer("q", [CHUNK], "en", "Demo Bank")
