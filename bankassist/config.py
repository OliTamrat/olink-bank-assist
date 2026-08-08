from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    database_url: str
    gemini_api_key: str | None
    gemini_model: str
    # Vertex AI: authenticates with the Cloud Run runtime service account via
    # Application Default Credentials, so there is no API key to store, leak
    # or rotate. Preferred over the AI Studio key path when both are set.
    use_vertex: bool
    vertex_project: str | None
    vertex_location: str
    app_base_url: str
    # The git commit this revision was built from, set by the deploy workflow.
    # Empty locally, which is honest: a dev server is not "a deployed commit".
    git_sha: str
    request_timeout: float
    log_level: str
    chat_rate_per_ip: int  # messages/minute per client IP; <=0 disables
    chat_rate_per_conversation: int  # messages/minute per conversation; <=0 disables
    # FAILED admin auth attempts per minute, per (tenant, client IP). Counts
    # failures only, never successful calls: an operator working a busy handoff
    # queue must never be throttled, and throttling them would be a denial of
    # service dressed up as a security control. <=0 disables.
    admin_auth_failures_per_ip: int
    # Whether the admin session cookie carries the Secure flag. Default TRUE
    # and only relaxed by an explicit opt-out, so a misconfiguration means
    # "login does not work locally" rather than "the session cookie went over
    # plain HTTP in production". Deliberately not inferred from the request
    # scheme: behind a TLS-terminating proxy the app sees http, so inference
    # would fail open in exactly the environment that matters.
    admin_cookie_secure: bool


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("BANKASSIST_DATABASE_URL", "sqlite:///bankassist.db"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        use_vertex=os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower()
        in {"1", "true", "yes", "on"},
        vertex_project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None,
        # A concrete region rather than "global": predictable latency, and a
        # defensible answer when a bank asks where inference happens — this
        # product is sold partly on data-residency discipline. "global" is
        # still accepted if set explicitly.
        vertex_location=os.environ.get("VERTEX_LOCATION", "us-central1"),
        app_base_url=os.environ.get("APP_BASE_URL", "http://localhost:8100"),
        git_sha=os.environ.get("BANKASSIST_GIT_SHA", ""),
        request_timeout=float(os.environ.get("BANKASSIST_REQUEST_TIMEOUT", "20")),
        log_level=os.environ.get("BANKASSIST_LOG_LEVEL", "INFO"),
        chat_rate_per_ip=int(os.environ.get("BANKASSIST_CHAT_RATE_PER_IP", "60")),
        chat_rate_per_conversation=int(
            os.environ.get("BANKASSIST_CHAT_RATE_PER_CONVERSATION", "20")
        ),
        admin_auth_failures_per_ip=int(
            os.environ.get("BANKASSIST_ADMIN_AUTH_FAILURES_PER_IP", "10")
        ),
        admin_cookie_secure=os.environ.get(
            "BANKASSIST_ADMIN_COOKIE_INSECURE", ""
        ).strip().lower() not in {"1", "true", "yes", "on"},
    )


def reset_settings() -> None:
    """Test hook: force settings to re-read the environment."""
    get_settings.cache_clear()
