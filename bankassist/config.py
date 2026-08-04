from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    database_url: str
    gemini_api_key: str | None
    gemini_model: str
    app_base_url: str
    request_timeout: float
    log_level: str
    chat_rate_per_ip: int  # messages/minute per client IP; <=0 disables
    chat_rate_per_conversation: int  # messages/minute per conversation; <=0 disables


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("BANKASSIST_DATABASE_URL", "sqlite:///bankassist.db"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        app_base_url=os.environ.get("APP_BASE_URL", "http://localhost:8100"),
        request_timeout=float(os.environ.get("BANKASSIST_REQUEST_TIMEOUT", "20")),
        log_level=os.environ.get("BANKASSIST_LOG_LEVEL", "INFO"),
        chat_rate_per_ip=int(os.environ.get("BANKASSIST_CHAT_RATE_PER_IP", "60")),
        chat_rate_per_conversation=int(
            os.environ.get("BANKASSIST_CHAT_RATE_PER_CONVERSATION", "20")
        ),
    )


def reset_settings() -> None:
    """Test hook: force settings to re-read the environment."""
    get_settings.cache_clear()
