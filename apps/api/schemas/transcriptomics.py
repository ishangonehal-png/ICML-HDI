from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .pathology import MethodMetadata


TranscriptomicsDataSource = Literal[
    "artifact",
    "modality_result",
    "counts_tsv",
    "unavailable",
]

TranscriptomicsCoverageDataSource = Literal[
    "artifact",
    "modality_result",
    "counts_tsv",
    "none",
]

TranscriptomicsAvailabilityCode = Literal[
    "available",
    "invalid_case_id",
    "missing_input",
    "insufficient_gene_coverage",
    "precompute_missing",
    "frozen_reference_unavailable",
    "evidence_unavailable",
]

TranscriptomicsPrecomputeSource = Literal["artifact", "modality_result", "none"]


class TranscriptomicsPrecomputeStatus(BaseModel):
    required: bool
    available: bool
    data_source: TranscriptomicsPrecomputeSource
    unavailable_reason: str | None = None
    run_id: str | None = None
    generated_at: str | None = None

    model_config = ConfigDict(extra="forbid")


class GepReferenceGovernance(BaseModel):
    required: bool
    available: bool
    valid: bool
    reference_id: str | None = None
    reference_sha256: str | None = None
    source_path: str | None = None
    unavailable_reason: str | None = None

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsMetricResponse(BaseModel):
    case_id: str
    value: float | None = None
    available: bool
    data_source: TranscriptomicsDataSource
    availability_code: TranscriptomicsAvailabilityCode
    unavailable_reason: str | None = None
    precompute: TranscriptomicsPrecomputeStatus | None = None
    gep_reference: GepReferenceGovernance | None = None
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_availability_consistency(self) -> "TranscriptomicsMetricResponse":
        if self.available and self.value is None:
            raise ValueError("available=true requires a numeric value")
        if not self.available and self.value is not None:
            raise ValueError("available=false requires value=null")
        if self.available and self.availability_code != "available":
            raise ValueError("available=true requires availability_code='available'")
        if not self.available and self.availability_code == "available":
            raise ValueError("available=false cannot use availability_code='available'")
        return self


class TranscriptomicsEvidenceGene(BaseModel):
    symbol: str
    normalized_count: float
    raw_tpm: float | None = Field(default=None, ge=0.0)

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsEvidenceQc(BaseModel):
    has_rna_input: bool
    gene_panel_size: int = Field(..., ge=0)
    genes_present: int = Field(..., ge=0)
    missing_genes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsEvidenceResponse(BaseModel):
    case_id: str
    top_genes: list[TranscriptomicsEvidenceGene] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    available: bool
    data_source: TranscriptomicsDataSource
    availability_code: TranscriptomicsAvailabilityCode
    unavailable_reason: str | None = None
    qc: TranscriptomicsEvidenceQc
    gep_reference: GepReferenceGovernance | None = None
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsDegVolcanoPoint(BaseModel):
    gene_symbol: str
    x: float
    y: float = Field(..., ge=0.0)
    log2_fc_proxy: float
    p_value_proxy: float = Field(..., gt=0.0, le=1.0)
    raw_tpm: float = Field(..., ge=0.0)
    reference_z: float | None = None
    direction: Literal["up", "down", "neutral"]
    significant: bool

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsDegVolcanoPlotConfig(BaseModel):
    x_axis_label: str
    y_axis_label: str
    x_threshold_abs: float = Field(..., ge=0.0)
    y_threshold: float = Field(..., ge=0.0)
    p_value_proxy: Literal[True] = True
    proxy_note: str
    total_genes_observed: int = Field(..., ge=0)
    returned_points: int = Field(..., ge=0)

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsDegVolcanoResponse(BaseModel):
    case_id: str
    available: bool
    data_source: TranscriptomicsDataSource
    availability_code: TranscriptomicsAvailabilityCode
    unavailable_reason: str | None = None
    points: list[TranscriptomicsDegVolcanoPoint] = Field(default_factory=list)
    plot: TranscriptomicsDegVolcanoPlotConfig
    gep_reference: GepReferenceGovernance | None = None
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsCaseCoverage(BaseModel):
    case_id: str
    has_rna_input: bool
    cyt_available: bool
    gep_available: bool
    tide_available: bool
    tide_precompute_available: bool
    tide_unavailable_reason: str | None = None
    evidence_available: bool
    missing_components: list[str] = Field(default_factory=list)
    mvp_ready: bool
    gep_reference_valid: bool
    gep_reference_required: bool
    gep_reference_id: str | None = None
    release_gate_blockers: list[str] = Field(default_factory=list)
    primary_data_source: TranscriptomicsCoverageDataSource

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsCoverageSummary(BaseModel):
    cases_total: int = Field(..., ge=0)
    cases_with_rna_input: int = Field(..., ge=0)
    cases_with_full_mvp_coverage: int = Field(..., ge=0)
    cases_missing_mvp_coverage: int = Field(..., ge=0)
    cases_with_tide: int = Field(..., ge=0)
    cases_missing_tide_precompute: int = Field(..., ge=0)
    cases_with_gep_reference_valid: int = Field(..., ge=0)
    cases_missing_gep_reference: int = Field(..., ge=0)

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsCoverageResponse(BaseModel):
    summary: TranscriptomicsCoverageSummary
    cases: list[TranscriptomicsCaseCoverage] = Field(default_factory=list)
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")


# ---- Sequencing plots (standard cancer transcriptomics visualizations) ----

TranscriptomicsPlotKind = Literal[
    "volcano",
    "ma_plot",
    "top_genes_bar",
    "signature_scores",
    "expression_heatmap",
    "raw_matrix_preview",
]


class TranscriptomicsMaPlotPoint(BaseModel):
    """Standard MA-plot point: mean expression (A) vs log2 fold-change (M)."""

    gene_symbol: str
    mean_expr_log2: float = Field(..., description="A = mean log2 expression (this case vs reference or median)")
    log2_fc: float = Field(..., description="M = log2 fold-change proxy")
    significant: bool = False

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsSignatureScoreBar(BaseModel):
    label: str
    value: float | None = None
    available: bool = True

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsHeatmapRow(BaseModel):
    label: str = Field(..., description="Row label, e.g. case_id")
    values: list[float] = Field(..., description="Expression value per gene (same order as gene_symbols)")

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsExpressionHeatmap(BaseModel):
    """Single-case or multi-case expression heatmap: rows = samples, columns = genes."""

    gene_symbols: list[str] = Field(default_factory=list)
    rows: list[TranscriptomicsHeatmapRow] = Field(default_factory=list)
    available: bool = False

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsRawExpressionMatrixRow(BaseModel):
    gene_symbol: str
    raw_value: float = Field(..., ge=0.0, description="Raw expression value from matrix source")
    normalized_log2: float = Field(..., description="log2(raw_value + 1.0) for relative comparison")
    rank: int = Field(..., ge=1, description="Descending rank by raw expression in observed genes")

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsRawExpressionMatrixPreview(BaseModel):
    available: bool = False
    data_source: TranscriptomicsDataSource = "unavailable"
    unavailable_reason: str | None = None
    total_genes_observed: int = Field(default=0, ge=0)
    returned_rows: int = Field(default=0, ge=0)
    preview_limit: int = Field(default=0, ge=0)
    truncated: bool = False
    rows: list[TranscriptomicsRawExpressionMatrixRow] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class TranscriptomicsPlotsResponse(BaseModel):
    """
    Unified sequencing plots payload for cancer transcriptomics.
    Standard plots: volcano (DEG), MA plot, top genes bar, signature scores bar, expression heatmap.
    """

    case_id: str
    available: bool = Field(..., description="True if any RNA input and at least one plot has data")

    volcano: TranscriptomicsDegVolcanoResponse | None = Field(
        default=None,
        description="Volcano plot: log2FC vs -log10(p) proxy",
    )
    ma_plot: list[TranscriptomicsMaPlotPoint] = Field(
        default_factory=list,
        description="MA plot: mean log2 expression vs log2FC (standard DESeq2-style)",
    )
    top_genes_bar: list[TranscriptomicsEvidenceGene] = Field(
        default_factory=list,
        description="Top genes for bar chart (normalized expression)",
    )
    signature_scores: list[TranscriptomicsSignatureScoreBar] = Field(
        default_factory=list,
        description="CYT / GEP / TIDE for bar chart",
    )
    expression_heatmap: TranscriptomicsExpressionHeatmap = Field(
        default_factory=lambda: TranscriptomicsExpressionHeatmap(available=False),
        description="Expression heatmap: genes × sample(s)",
    )
    raw_matrix_preview: TranscriptomicsRawExpressionMatrixPreview = Field(
        default_factory=TranscriptomicsRawExpressionMatrixPreview,
        description="Bounded preview of raw gene expression matrix values",
    )

    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")
