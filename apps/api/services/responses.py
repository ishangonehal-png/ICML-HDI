from __future__ import annotations

from typing import Any


def research_stub_response(
    *,
    id_key: str,
    id_value: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build consistent research-only placeholder payloads for scaffolded routes."""
    payload: dict[str, Any] = {
        id_key: id_value,
        "status": "stub",
        "message": message,
        "research_use_only": True,
    }
    if extra:
        payload.update(extra)
    return payload
