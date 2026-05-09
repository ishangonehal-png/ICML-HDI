"""Reusable service helpers for API routers."""

from .cases import ensure_case_exists
from .cohort_cases import list_overlapping_cohort_cases
from .clinical import (
    build_clinical_metadata,
    clear_clinical_trial_match_cache,
    get_clinical_eligibility,
    get_clinical_patient_summary,
    get_clinical_survival,
    get_clinical_survival_baseline,
    get_clinical_trial_matches,
)
from .pathology import (
    PathologyDataUnavailableError,
    build_pathology_metadata,
    derive_case_id_from_slide_id,
    get_evidence,
    get_heatmap,
    get_tissue_composition,
)
from .pathology_assets import (
    EnsoProxyError,
    EnsoSlideResolution,
    enso_api_base_url,
    load_heatmap_image,
    load_slide_preview_image,
    proxy_enso_asset,
    resolve_enso_slide_id,
    resolve_enso_slide_status,
    resolve_heatmap_path,
    resolve_heatmap_uri,
    resolve_slide_path,
    resolve_slide_uri,
)
from .pathology_id_resolution import derive_short_case_id, derive_short_slide_id
from .responses import research_stub_response
from .io_score import build_io_score_metadata, get_io_immune_score
from .io_similar import get_io_similar_cases, invalidate_cohort_cache
from .fusion import (
    build_fusion_metadata,
    get_fusion_attribution,
    get_fusion_score,
    get_fusion_similar_cases,
)
from .agent_context import build_agent_context
from .analysis_queue import (
    AnalysisQueueUnavailableError,
    enqueue_analysis_job,
    requeue_inflight_analysis_jobs,
)
from .analysis_worker import process_analysis_job, run_worker
from .transcriptomics import (
    build_transcriptomics_metadata,
    get_cyt_signature,
    get_deg_volcano,
    get_gep_signature,
    get_tide_signature,
    get_transcriptomic_evidence,
    get_transcriptomics_coverage_report,
    get_transcriptomics_plots,
)

__all__ = [
    "ensure_case_exists",
    "list_overlapping_cohort_cases",
    "research_stub_response",
    "derive_case_id_from_slide_id",
    "derive_short_case_id",
    "derive_short_slide_id",
    "PathologyDataUnavailableError",
    "build_pathology_metadata",
    "get_tissue_composition",
    "get_heatmap",
    "get_evidence",
    "get_io_immune_score",
    "build_io_score_metadata",
    "get_io_similar_cases",
    "invalidate_cohort_cache",
    "build_fusion_metadata",
    "get_fusion_score",
    "get_fusion_attribution",
    "get_fusion_similar_cases",
    "build_agent_context",
    "enqueue_analysis_job",
    "requeue_inflight_analysis_jobs",
    "AnalysisQueueUnavailableError",
    "process_analysis_job",
    "run_worker",
    "build_transcriptomics_metadata",
    "get_cyt_signature",
    "get_deg_volcano",
    "get_gep_signature",
    "get_tide_signature",
    "get_transcriptomic_evidence",
    "get_transcriptomics_coverage_report",
    "get_transcriptomics_plots",
    "build_clinical_metadata",
    "clear_clinical_trial_match_cache",
    "get_clinical_patient_summary",
    "get_clinical_eligibility",
    "get_clinical_survival",
    "get_clinical_survival_baseline",
    "get_clinical_trial_matches",
    "load_heatmap_image",
    "load_slide_preview_image",
    "resolve_heatmap_path",
    "resolve_heatmap_uri",
    "resolve_slide_path",
    "resolve_slide_uri",
    "resolve_enso_slide_id",
    "resolve_enso_slide_status",
    "enso_api_base_url",
    "proxy_enso_asset",
    "EnsoProxyError",
    "EnsoSlideResolution",
]
