"""FastAPI route modules and registration helpers."""

from __future__ import annotations

from fastapi import FastAPI

from . import agent, analysis, clinical, cohort, fusion, health, io_immune, pathology, transcriptomics, uploads

_API_V1_ROUTERS = [
    cohort.router,
    uploads.router,
    analysis.router,
    pathology.router,
    transcriptomics.router,
    clinical.router,
    fusion.router,
    io_immune.router,
    agent.router,
]


def register_routers(app: FastAPI, *, api_prefix: str) -> None:
    app.include_router(health.router)
    for router in _API_V1_ROUTERS:
        app.include_router(router, prefix=api_prefix)


__all__ = [
    "health",
    "cohort",
    "uploads",
    "analysis",
    "pathology",
    "transcriptomics",
    "clinical",
    "fusion",
    "io_immune",
    "agent",
    "register_routers",
]
