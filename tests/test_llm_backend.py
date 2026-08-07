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


def _use_vertex(monkeypatch: pytest.MonkeyPatch, location: str = "us-central1") -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "olink-bank-assist")
    monkeypatch.setenv("VERTEX_LOCATION", location)
    config.reset_settings()
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
