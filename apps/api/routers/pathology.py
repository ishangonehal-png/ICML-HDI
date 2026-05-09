from __future__ import annotations

import os
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Query, Response

from schemas.pathology import (
    PathologyEvidenceResponse,
    PathologyHeatmapResponse,
    PathologyTissueCompositionResponse,
    PathologyViewerConfigResponse,
)
from services import (
    EnsoProxyError,
    PathologyDataUnavailableError,
    get_evidence,
    get_heatmap,
    get_tissue_composition,
    load_heatmap_image,
    load_slide_preview_image,
    proxy_enso_asset,
    resolve_enso_slide_id,
    resolve_enso_slide_status,
)

router = APIRouter(prefix="/pathology", tags=["pathology"])

_CACHE_FORWARD_HEADERS = (
    "Cache-Control",
    "ETag",
    "Last-Modified",
)
_HEATMAP_FORWARD_HEADERS = (
    *_CACHE_FORWARD_HEADERS,
    "X-Model-Id",
    "X-Model-Name",
    "X-Slide-Width",
    "X-Slide-Height",
    "X-Coverage-Width",
    "X-Coverage-Height",
)

_TILE_CACHE_BUST_ENV = "PATHOLOGY_TILE_CACHE_BUST"

# OpenSeadragon tile/image requests are fetched as image resources and can bypass
# standard CORS middleware header injection depending on browser request mode.
# Ensure pathology image/tile responses are always explicitly cross-origin readable.
_CROSS_ORIGIN_ASSET_HEADERS = {
    "Cross-Origin-Resource-Policy": "cross-origin",
    # Avoid stale browser tile caches persisting old header behavior across redeploys.
    "Cache-Control": "no-store",
}


def _append_cache_bust(url: str) -> str:
    token = os.getenv(_TILE_CACHE_BUST_ENV, "").strip()
    if not token:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}v={token}"


def _proxy_enso_response(
    *,
    path: str,
    query_params: Mapping[str, Any] | None = None,
    forward_headers: tuple[str, ...] = (),
) -> Response:
    try:
        proxied_payload = proxy_enso_asset(
            path=path,
            query_params=query_params,
            forward_headers=forward_headers,
        )
    except EnsoProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    response_headers = dict(proxied_payload.headers)
    response_headers.update(_CROSS_ORIGIN_ASSET_HEADERS)

    return Response(
        content=proxied_payload.content,
        media_type=proxied_payload.media_type,
        headers=response_headers,
    )


def _raise_pathology_missing(exc: PathologyDataUnavailableError) -> None:
    raise HTTPException(status_code=404, detail=exc.detail) from exc


def _resolve_fallback_asset_urls(slide_id: str) -> tuple[str | None, str | None]:
    fallback_heatmap_url: str | None = None
    fallback_preview_url: str | None = None

    heatmap_available = load_heatmap_image(slide_id) is not None
    if heatmap_available:
        fallback_heatmap_url = _append_cache_bust(f"/v1/pathology/slides/{slide_id}/heatmap/image")
        # preview/image transparently falls back to the heatmap when no WSI preview exists.
        fallback_preview_url = _append_cache_bust(f"/v1/pathology/slides/{slide_id}/preview/image")
        return fallback_preview_url, fallback_heatmap_url

    preview_payload, _ = load_slide_preview_image(slide_id)
    if preview_payload is not None:
        fallback_preview_url = _append_cache_bust(f"/v1/pathology/slides/{slide_id}/preview/image")

    return fallback_preview_url, fallback_heatmap_url


@router.get("/slides/{slide_id}/tissue-composition", response_model=PathologyTissueCompositionResponse)
def get_tissue_composition_route(
    slide_id: str,
    strict_missing: bool | None = Query(
        default=None,
        description="When true, disables deterministic fallback and requires schema-valid artifact-backed pathology data.",
    ),
) -> PathologyTissueCompositionResponse:
    try:
        return get_tissue_composition(slide_id, strict_missing=strict_missing)
    except PathologyDataUnavailableError as exc:
        _raise_pathology_missing(exc)


@router.get("/slides/{slide_id}/heatmap", response_model=PathologyHeatmapResponse)
def get_slide_heatmap(
    slide_id: str,
    strict_missing: bool | None = Query(
        default=None,
        description="When true, disables deterministic fallback and requires schema-valid artifact-backed pathology data.",
    ),
) -> PathologyHeatmapResponse:
    try:
        return get_heatmap(slide_id, strict_missing=strict_missing)
    except PathologyDataUnavailableError as exc:
        _raise_pathology_missing(exc)


@router.get("/slides/{slide_id}/heatmap/image")
def get_slide_heatmap_image(slide_id: str) -> Response:
    image_payload = load_heatmap_image(slide_id)
    if image_payload is None:
        raise HTTPException(status_code=404, detail=f"No heatmap image found for slide '{slide_id}'.")
    return Response(
        content=image_payload.content,
        media_type=image_payload.media_type,
        headers=_CROSS_ORIGIN_ASSET_HEADERS,
    )


@router.get("/slides/{slide_id}/preview/image")
def get_slide_preview_image(slide_id: str) -> Response:
    image_payload, error_detail = load_slide_preview_image(slide_id)
    if image_payload is None:
        detail = error_detail or f"No preview image found for slide '{slide_id}'."
        raise HTTPException(status_code=404, detail=detail)
    return Response(
        content=image_payload.content,
        media_type=image_payload.media_type,
        headers=_CROSS_ORIGIN_ASSET_HEADERS,
    )


@router.get("/slides/{slide_id}/dzi")
def get_slide_dzi(slide_id: str) -> Response:
    enso_slide_id = resolve_enso_slide_id(slide_id)
    return _proxy_enso_response(
        path=f"/api/slides/{enso_slide_id}/dzi",
        forward_headers=_CACHE_FORWARD_HEADERS,
    )


@router.get("/slides/{slide_id}/tile/{level}/{tile_name}")
def get_slide_tile(slide_id: str, level: int, tile_name: str) -> Response:
    enso_slide_id = resolve_enso_slide_id(slide_id)
    return _proxy_enso_response(
        path=f"/api/slides/{enso_slide_id}/dzi_files/{level}/{tile_name}",
        forward_headers=_CACHE_FORWARD_HEADERS,
    )


@router.get("/slides/{slide_id}/attention-heatmap")
def get_slide_attention_heatmap(
    slide_id: str,
    model_id: str = Query(default="lung_stage"),
    level: int = Query(default=2, ge=0),
    smooth: bool = Query(default=True),
    alpha_power: float = Query(default=0.7, gt=0.0),
) -> Response:
    enso_slide_id = resolve_enso_slide_id(slide_id)
    return _proxy_enso_response(
        path=f"/api/heatmap/{enso_slide_id}/{model_id}",
        query_params={
            "level": level,
            "smooth": smooth,
            "alpha_power": alpha_power,
        },
        forward_headers=_HEATMAP_FORWARD_HEADERS,
    )


@router.get("/slides/{slide_id}/viewer-config", response_model=PathologyViewerConfigResponse)
def get_slide_viewer_config(
    slide_id: str,
    model_id: str = Query(default="lung_stage"),
    level: int = Query(default=2, ge=0),
    smooth: bool = Query(default=True),
    alpha_power: float = Query(default=0.7, gt=0.0),
) -> PathologyViewerConfigResponse:
    deepzoom_status = resolve_enso_slide_status(slide_id)

    if deepzoom_status.deepzoom_available:
        fallback_preview_url = _append_cache_bust(f"/v1/pathology/slides/{slide_id}/preview/image")
        fallback_heatmap_url = _append_cache_bust(f"/v1/pathology/slides/{slide_id}/heatmap/image")
    else:
        fallback_preview_url, fallback_heatmap_url = _resolve_fallback_asset_urls(slide_id)

    return PathologyViewerConfigResponse(
        slide_id=slide_id,
        enso_slide_id=deepzoom_status.resolved_slide_id,
        deepzoom_available=deepzoom_status.deepzoom_available,
        deepzoom_unavailable_reason=deepzoom_status.unavailable_reason,
        dzi_url=_append_cache_bust(f"/v1/pathology/slides/{slide_id}/dzi"),
        tile_url_template=_append_cache_bust(f"/v1/pathology/slides/{slide_id}/tile/{{level}}/{{tile_name}}"),
        attention_heatmap_url=_append_cache_bust(f"/v1/pathology/slides/{slide_id}/attention-heatmap"),
        fallback_preview_url=fallback_preview_url,
        fallback_heatmap_url=fallback_heatmap_url,
        defaults={
            "model_id": model_id,
            "level": level,
            "smooth": smooth,
            "alpha_power": alpha_power,
        },
    )


@router.post("/slides/{slide_id}/evidence", response_model=PathologyEvidenceResponse)
def get_pathology_evidence(
    slide_id: str,
    strict_missing: bool | None = Query(
        default=None,
        description="When true, disables deterministic fallback and requires schema-valid artifact-backed pathology data.",
    ),
) -> PathologyEvidenceResponse:
    try:
        return get_evidence(slide_id, strict_missing=strict_missing)
    except PathologyDataUnavailableError as exc:
        _raise_pathology_missing(exc)
