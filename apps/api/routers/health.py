from __future__ import annotations

from fastapi import APIRouter

from core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "research_use_only": True,
        "agent_llm_configured": bool((settings.openai_api_key or "").strip()),
    }
