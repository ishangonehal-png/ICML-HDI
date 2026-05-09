from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from db.session import init_db
from routers import register_routers


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize application resources at startup."""
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Research-only backend scaffold for the YC AIxBio hackathon. "
            "Outputs are proxy estimates and not clinical predictions."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_research_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Research-Use-Only"] = "true"
        response.headers["X-Clinical-Use"] = "not-intended"

        # Pathology tile/asset requests are fetched by OpenSeadragon as image
        # resources and may surface browser-side CORS errors unless headers are
        # present on *all* responses, including errors (e.g. 404 tiles).
        path = request.url.path
        if path.startswith(f"{settings.api_v1_prefix}/pathology/slides/") and (
            "/tile/" in path
            or path.endswith("/dzi")
            or path.endswith("/preview/image")
            or path.endswith("/heatmap/image")
            or path.endswith("/attention-heatmap")
        ):
            origin = request.headers.get("origin", "").strip()
            if origin:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Vary"] = "Origin"
            else:
                response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"

        return response

    register_routers(app, api_prefix=settings.api_v1_prefix)

    return app


app = create_app()
