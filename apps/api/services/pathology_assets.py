from __future__ import annotations

import io
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import httpx

from .pathology_id_resolution import (
    derive_case_id_from_slide_id,
    derive_short_case_id,
    derive_short_slide_id,
    resolve_heatmap_file,
    resolve_wsi_file,
)

_HEATMAP_DIR_ENV = "PATHOLOGY_HEATMAP_DIR"
_WSI_DIR_ENV = "PATHOLOGY_WSI_DIR"
_PREVIEW_MAX_EDGE = 1024

_ENSO_API_BASE_URL_ENV = "ENSO_API_BASE_URL"
_DEFAULT_ENSO_API_BASE_URL = "http://127.0.0.1:8003"
_ENSO_EMBEDDINGS_DIR_ENV = "ENSO_EMBEDDINGS_DIR"
_TCGA_FULL475_ROOT_ENV = "TCGA_FULL475_ROOT"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ENSO_EMBEDDINGS_DIR = _REPO_ROOT / "data" / "luad" / "embeddings" / "level0"
_ENSO_PROXY_TIMEOUT_SECONDS = 20.0
_DX1_TOKEN_PATTERN = re.compile(r"(?:^|[-_.])DX1(?:$|[-_.])", re.IGNORECASE)


@dataclass(frozen=True)
class ImagePayload:
    content: bytes
    media_type: str


@dataclass(frozen=True)
class ProxyBinaryPayload:
    content: bytes
    media_type: str
    headers: dict[str, str]


class EnsoProxyError(RuntimeError):
    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _asset_directory(env_var: str) -> Path | None:
    directory = os.getenv(env_var, "").strip()
    if not directory:
        return None

    path = Path(directory)
    if not path.is_dir():
        return None
    return path


def _identifier_candidates(slide_id: str) -> list[str]:
    case_id = derive_case_id_from_slide_id(slide_id)
    if case_id and case_id != slide_id:
        return [slide_id, case_id]
    return [slide_id]


def _resolve_asset_path(
    *,
    slide_id: str,
    env_var: str,
    resolver: Callable[[Path, str], Path | None],
) -> Path | None:
    asset_dir = _asset_directory(env_var)
    if asset_dir is None:
        return None

    for identifier in _identifier_candidates(slide_id):
        resolved = resolver(asset_dir, identifier)
        if resolved is not None:
            return resolved
    return None


def resolve_heatmap_path(slide_id: str) -> Path | None:
    return _resolve_asset_path(
        slide_id=slide_id,
        env_var=_HEATMAP_DIR_ENV,
        resolver=resolve_heatmap_file,
    )


def resolve_slide_path(slide_id: str) -> Path | None:
    return _resolve_asset_path(
        slide_id=slide_id,
        env_var=_WSI_DIR_ENV,
        resolver=resolve_wsi_file,
    )


def _infer_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(path.name)
    if media_type and media_type.startswith("image/"):
        return media_type
    return "application/octet-stream"


def _read_image_payload(path: Path) -> ImagePayload | None:
    try:
        return ImagePayload(content=path.read_bytes(), media_type=_infer_media_type(path))
    except OSError:
        return None


def load_heatmap_image(slide_id: str) -> ImagePayload | None:
    heatmap_path = resolve_heatmap_path(slide_id)
    if heatmap_path is None:
        return None
    return _read_image_payload(heatmap_path)


def _generate_wsi_preview(slide_path: Path) -> tuple[ImagePayload | None, str | None]:
    try:
        import openslide  # type: ignore[import-untyped]
    except Exception:
        return None, "OpenSlide is unavailable; cannot generate preview from WSI."

    try:
        with openslide.OpenSlide(str(slide_path)) as slide:
            width, height = slide.dimensions
            if width <= 0 or height <= 0:
                return None, "WSI has invalid dimensions."

            target_downsample = max(width / _PREVIEW_MAX_EDGE, height / _PREVIEW_MAX_EDGE, 1.0)
            level = slide.get_best_level_for_downsample(target_downsample)
            level_width, level_height = slide.level_dimensions[level]
            preview_image = slide.read_region((0, 0), level, (level_width, level_height)).convert("RGB")
    except Exception as exc:
        return None, f"Failed to generate WSI preview: {type(exc).__name__}."

    preview_image.thumbnail((_PREVIEW_MAX_EDGE, _PREVIEW_MAX_EDGE))
    output_buffer = io.BytesIO()
    try:
        preview_image.save(output_buffer, format="JPEG", quality=85)
    except Exception as exc:
        return None, f"Failed to encode WSI preview image: {type(exc).__name__}."

    return ImagePayload(content=output_buffer.getvalue(), media_type="image/jpeg"), None


def load_slide_preview_image(slide_id: str) -> tuple[ImagePayload | None, str | None]:
    slide_path = resolve_slide_path(slide_id)
    if slide_path is not None:
        preview_payload, preview_error = _generate_wsi_preview(slide_path)
        if preview_payload is not None:
            return preview_payload, None

        heatmap_payload = load_heatmap_image(slide_id)
        if heatmap_payload is not None:
            return heatmap_payload, None
        return None, preview_error

    heatmap_payload = load_heatmap_image(slide_id)
    if heatmap_payload is not None:
        return heatmap_payload, None
    return None, "No WSI or heatmap image assets are available for this slide."


def resolve_heatmap_uri(slide_id: str) -> str | None:
    heatmap_path = resolve_heatmap_path(slide_id)
    if heatmap_path is None:
        return None
    return heatmap_path.resolve().as_uri()


def resolve_slide_uri(slide_id: str) -> str | None:
    slide_path = resolve_slide_path(slide_id)
    if slide_path is None:
        return None
    return slide_path.resolve().as_uri()


def _default_enso_embeddings_dir() -> Path:
    configured_full475_root = os.getenv(_TCGA_FULL475_ROOT_ENV, "").strip()
    if configured_full475_root:
        return Path(configured_full475_root).expanduser() / "embeddings" / "level0"
    return _DEFAULT_ENSO_EMBEDDINGS_DIR


def _enso_embeddings_directory() -> Path | None:
    configured_dir = os.getenv(_ENSO_EMBEDDINGS_DIR_ENV, "").strip()
    if configured_dir:
        directory = Path(configured_dir).expanduser()
    else:
        directory = _default_enso_embeddings_dir()

    if not directory.is_dir():
        return None
    return directory


@dataclass(frozen=True)
class EmbeddingCandidate:
    stem: str
    is_symlink: bool
    depth_rank: int
    relative_path: str


@dataclass(frozen=True)
class EnsoSlideResolution:
    requested_slide_id: str
    resolved_slide_id: str
    deepzoom_available: bool
    unavailable_reason: str | None = None


def _embedding_candidates(directory: Path) -> list[EmbeddingCandidate]:
    candidates: list[EmbeddingCandidate] = []

    for embedding_path in sorted(directory.rglob("*.npy")):
        if embedding_path.name.endswith("_coords.npy"):
            continue
        try:
            relative = embedding_path.relative_to(directory)
        except ValueError:
            relative = embedding_path
        candidates.append(
            EmbeddingCandidate(
                stem=embedding_path.stem,
                is_symlink=embedding_path.is_symlink(),
                depth_rank=len(relative.parts),
                relative_path=relative.as_posix(),
            )
        )

    return candidates


def _contains_dx1(identifier: str) -> bool:
    return _DX1_TOKEN_PATTERN.search(identifier) is not None


def _resolve_enso_candidates(slide_id: str, embedding_candidates: list[EmbeddingCandidate]) -> list[str]:
    normalized_input = slide_id.strip()
    if not normalized_input:
        return []

    normalized_input_lower = normalized_input.lower()
    short_slide_id = derive_short_slide_id(normalized_input)
    short_slide_lower = short_slide_id.lower()
    short_case_id = derive_short_case_id(normalized_input)
    short_case_lower = short_case_id.lower()

    scored: list[tuple[tuple[int, int, int, int, str, str], str]] = []
    for candidate_record in embedding_candidates:
        candidate = candidate_record.stem
        candidate_lower = candidate.lower()
        candidate_short_slide = derive_short_slide_id(candidate).lower()
        candidate_short_case = derive_short_case_id(candidate).lower()

        if candidate_lower == normalized_input_lower:
            match_rank = 0
        elif short_slide_lower and candidate_short_slide == short_slide_lower:
            match_rank = 1
        elif short_case_lower and candidate_short_case == short_case_lower:
            match_rank = 2
        elif short_slide_lower and short_slide_lower in candidate_lower:
            match_rank = 3
        elif normalized_input_lower in candidate_lower:
            match_rank = 4
        else:
            continue

        symlink_rank = 1 if candidate_record.is_symlink else 0
        dx1_rank = 0 if _contains_dx1(candidate) else 1
        scored.append(
            (
                (
                    symlink_rank,
                    match_rank,
                    dx1_rank,
                    candidate_record.depth_rank,
                    candidate_lower,
                    candidate_record.relative_path.lower(),
                ),
                candidate,
            )
        )

    scored.sort(key=lambda item: item[0])
    return [candidate for _, candidate in scored]


def resolve_enso_slide_status(slide_id: str) -> EnsoSlideResolution:
    """Resolve Enso deep-zoom availability and normalized slide id for a request."""
    normalized_slide_id = slide_id.strip()
    if not normalized_slide_id:
        return EnsoSlideResolution(
            requested_slide_id=slide_id,
            resolved_slide_id=normalized_slide_id,
            deepzoom_available=False,
            unavailable_reason="slide_id is empty.",
        )

    embeddings_dir = _enso_embeddings_directory()
    if embeddings_dir is None:
        return EnsoSlideResolution(
            requested_slide_id=normalized_slide_id,
            resolved_slide_id=normalized_slide_id,
            deepzoom_available=False,
            unavailable_reason=(
                "Enso embeddings directory is unavailable; configure "
                f"{_ENSO_EMBEDDINGS_DIR_ENV} or {_TCGA_FULL475_ROOT_ENV}."
            ),
        )

    embedding_candidates = _embedding_candidates(embeddings_dir)
    if not embedding_candidates:
        return EnsoSlideResolution(
            requested_slide_id=normalized_slide_id,
            resolved_slide_id=normalized_slide_id,
            deepzoom_available=False,
            unavailable_reason="No Enso embedding files were found for deep-zoom resolution.",
        )

    resolved_candidates = _resolve_enso_candidates(normalized_slide_id, embedding_candidates)
    if not resolved_candidates:
        return EnsoSlideResolution(
            requested_slide_id=normalized_slide_id,
            resolved_slide_id=normalized_slide_id,
            deepzoom_available=False,
            unavailable_reason=(
                "Slide is not indexed in Enso embeddings; deep-zoom is unavailable "
                "for this request."
            ),
        )

    return EnsoSlideResolution(
        requested_slide_id=normalized_slide_id,
        resolved_slide_id=resolved_candidates[0],
        deepzoom_available=True,
        unavailable_reason=None,
    )


def resolve_enso_slide_id(slide_id: str) -> str:
    """
    Resolve request slide identifiers to Enso's full slide id variant.

    Falls back to the original input when no Enso embedding-backed match can be
    found.
    """
    return resolve_enso_slide_status(slide_id).resolved_slide_id


def enso_api_base_url() -> str:
    configured = os.getenv(_ENSO_API_BASE_URL_ENV, _DEFAULT_ENSO_API_BASE_URL).strip()
    if not configured:
        return _DEFAULT_ENSO_API_BASE_URL
    return configured.rstrip("/")


def _normalize_query_params(query_params: Mapping[str, Any] | None) -> dict[str, str]:
    if not query_params:
        return {}

    normalized: dict[str, str] = {}
    for key, value in query_params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            normalized[key] = "true" if value else "false"
            continue
        normalized[key] = str(value)
    return normalized


def _build_enso_target_url(base_url: str, path: str) -> str:
    normalized_path = f"/{path.lstrip('/')}"
    normalized_base = base_url.rstrip("/")

    # Accept ENSO_API_BASE_URL values with or without trailing "/api".
    if normalized_path.startswith("/api/") and normalized_base.lower().endswith("/api"):
        normalized_path = normalized_path[len("/api") :]

    return f"{normalized_base}{normalized_path}"


def proxy_enso_asset(
    *,
    path: str,
    query_params: Mapping[str, Any] | None = None,
    timeout_seconds: float = _ENSO_PROXY_TIMEOUT_SECONDS,
    forward_headers: Iterable[str] = (),
) -> ProxyBinaryPayload:
    base_url = enso_api_base_url()
    target_url = _build_enso_target_url(base_url, path)
    headers_to_forward = tuple(forward_headers)

    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0))) as client:
            response = client.get(target_url, params=_normalize_query_params(query_params))
    except httpx.RequestError as exc:
        raise EnsoProxyError(
            status_code=502,
            detail=f"Failed to contact Enso API at '{base_url}'.",
        ) from exc

    if response.status_code >= 400:
        upstream_detail = response.text.strip()
        if not upstream_detail:
            upstream_detail = f"Enso API request failed with status {response.status_code}."

        status_code = response.status_code if 400 <= response.status_code <= 599 else 502
        raise EnsoProxyError(status_code=status_code, detail=upstream_detail)

    forwarded_response_headers: dict[str, str] = {}
    for header_name in headers_to_forward:
        header_value = response.headers.get(header_name)
        if header_value is None:
            continue
        forwarded_response_headers[header_name] = header_value

    media_type = response.headers.get("content-type") or "application/octet-stream"
    return ProxyBinaryPayload(
        content=response.content,
        media_type=media_type,
        headers=forwarded_response_headers,
    )
