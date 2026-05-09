from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

_DEFAULT_CORS_ALLOW_ORIGINS: tuple[str, ...] = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)


def _read_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    token = value.strip()
    if not token:
        return default
    try:
        return int(token)
    except ValueError:
        return default


def _read_csv_list(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default

    parsed = tuple(entry.strip() for entry in value.split(",") if entry.strip())
    if not parsed:
        return default

    return parsed


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    app_name: str
    app_env: str
    api_v1_prefix: str
    database_url: str
    redis_url: str
    analysis_queue_key: str
    analysis_queue_processing_key: str
    analysis_queue_dedupe_ttl_seconds: int
    analysis_worker_poll_timeout_seconds: int
    analysis_worker_requeue_inflight_on_start: bool
    auto_create_tables: bool
    cors_allow_origins: tuple[str, ...]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "YC AIxBio Research API"),
        app_env=os.getenv("APP_ENV", "development"),
        api_v1_prefix=os.getenv("API_V1_PREFIX", "/v1"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/aixbio",
        ),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        analysis_queue_key=os.getenv("ANALYSIS_QUEUE_KEY", "aixbio:analysis:jobs"),
        analysis_queue_processing_key=os.getenv(
            "ANALYSIS_QUEUE_PROCESSING_KEY",
            "aixbio:analysis:jobs:processing",
        ),
        analysis_queue_dedupe_ttl_seconds=_read_int(
            os.getenv("ANALYSIS_QUEUE_DEDUPE_TTL_SECONDS"),
            86_400,
        ),
        analysis_worker_poll_timeout_seconds=_read_int(
            os.getenv("ANALYSIS_WORKER_POLL_TIMEOUT_SECONDS"),
            5,
        ),
        analysis_worker_requeue_inflight_on_start=_read_bool(
            os.getenv("ANALYSIS_WORKER_REQUEUE_INFLIGHT_ON_START"),
            True,
        ),
        auto_create_tables=_read_bool(os.getenv("AUTO_CREATE_TABLES"), True),
        cors_allow_origins=_read_csv_list(
            os.getenv("CORS_ALLOW_ORIGINS"),
            _DEFAULT_CORS_ALLOW_ORIGINS,
        ),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )


settings = get_settings()
