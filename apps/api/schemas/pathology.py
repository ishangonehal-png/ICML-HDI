from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MethodMetadata(BaseModel):
    method: str
    version: str
    timestamp: str
    proxy_estimate: Literal[True] = True

    model_config = ConfigDict(extra="forbid")


PathologyDataSource = Literal["artifact", "seglung", "deterministic_fallback"]


class PathologyProvenance(BaseModel):
    data_source: PathologyDataSource
    resolver_strategy: str
    artifact_path: str | None = None
    source_path: str | None = None
    artifact_sha256: str | None = None
    artifact_updated_at: str | None = None
    model_id: str | None = None
    tile_encoder_model_id: str | None = None
    checkpoint_sha256: str | None = None
    run_id: str | None = None
    embedding_source_id: str | None = None

    model_config = ConfigDict(extra="forbid")


class TissueFraction(BaseModel):
    tissue: str
    fraction: float = Field(..., ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")


class PathologyQc(BaseModel):
    coverage: float = Field(..., ge=0.0, le=1.0)
    artifact_warning: str | None = None

    model_config = ConfigDict(extra="forbid")


class PathologyTissueCompositionResponse(BaseModel):
    case_id: str
    slide_id: str
    fractions: list[TissueFraction]
    qc: PathologyQc
    meta: MethodMetadata
    provenance: PathologyProvenance

    model_config = ConfigDict(extra="forbid")


class ViewportHint(BaseModel):
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    width: float = Field(..., ge=0.0, le=1.0)
    height: float = Field(..., ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")


class PathologyHeatmapResponse(BaseModel):
    case_id: str
    slide_id: str
    heatmap_uri: str
    slide_preview_uri: str | None = None
    viewport_hint: ViewportHint
    meta: MethodMetadata
    provenance: PathologyProvenance

    model_config = ConfigDict(extra="forbid")


class TileCoordinates(BaseModel):
    row: int = Field(..., ge=0)
    col: int = Field(..., ge=0)
    one_based_index: bool

    model_config = ConfigDict(extra="forbid")


class EvidenceTile(BaseModel):
    tile_id: str
    score: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    bbox: ViewportHint | None = None
    tile_coordinates: TileCoordinates | None = None

    model_config = ConfigDict(extra="forbid")


class PathologyEvidenceResponse(BaseModel):
    case_id: str
    slide_id: str
    top_tiles: list[EvidenceTile]
    meta: MethodMetadata
    provenance: PathologyProvenance

    model_config = ConfigDict(extra="forbid")


class PathologyViewerDefaults(BaseModel):
    model_id: str
    level: int = Field(..., ge=0)
    smooth: bool
    alpha_power: float = Field(..., gt=0.0)

    model_config = ConfigDict(extra="forbid")


class PathologyViewerConfigResponse(BaseModel):
    slide_id: str
    enso_slide_id: str
    deepzoom_available: bool
    deepzoom_unavailable_reason: str | None = None
    dzi_url: str
    tile_url_template: str
    attention_heatmap_url: str
    fallback_preview_url: str | None = None
    fallback_heatmap_url: str | None = None
    defaults: PathologyViewerDefaults

    model_config = ConfigDict(extra="forbid")
