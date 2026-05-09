export type UploadModality = "pathology" | "transcriptomics" | "clinical";
export type ModalityKey = UploadModality | "fusion" | "evidence_packaging";
export type JobState = "queued" | "running" | "completed" | "failed";

export interface MethodMetadata {
  method: string;
  version: string;
  timestamp: string;
  proxy_estimate: true;
}

export interface UploadInitRequest {
  case_id?: string;
  source: "cohort_select" | "file_upload";
}

export interface UploadInitResponse {
  session_id: string;
  accepted_modalities: UploadModality[];
  research_only: true;
}

export interface UploadFileDescriptor {
  file_name: string;
  modality: UploadModality;
  size_bytes: number;
  mime_type?: string;
}

export interface UploadFilesRequest {
  session_id: string;
  files: UploadFileDescriptor[];
}

export interface UploadFilesResponse {
  session_id: string;
  file_status: Array<{
    file_name: string;
    modality: UploadModality;
    status: "accepted" | "rejected";
    reason?: string;
  }>;
}

export type AnalysisStepKey =
  | "queue"
  | "pathology"
  | "transcriptomics"
  | "clinical"
  | "fusion"
  | "evidence_packaging";

export interface AnalysisStepStatus {
  key: AnalysisStepKey;
  label: string;
  status: JobState;
  detail?: string;
}

export interface AnalysisJobEvent {
  event_type: string;
  message: string;
  created_at?: string;
  payload?: Record<string, unknown>;
}

export interface AnalysisJobCreateRequest {
  session_id: string;
  case_id: string;
}

export interface AnalysisJobResponse {
  job_id: string;
  case_id: string;
  state: JobState;
  created_at: string;
  updated_at: string;
  steps: AnalysisStepStatus[];
  events?: AnalysisJobEvent[];
  errors?: string[];
  research_only: true;
}

export interface PathologyTissueCompositionResponse {
  case_id: string;
  slide_id: string;
  fractions: Array<{
    tissue: string;
    fraction: number;
  }>;
  qc: {
    coverage: number;
    artifact_warning?: string;
  };
  meta: MethodMetadata;
}

export interface PathologyHeatmapResponse {
  case_id: string;
  slide_id: string;
  heatmap_uri: string;
  slide_preview_uri?: string | null;
  viewport_hint: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  meta: MethodMetadata;
}

export interface PathologyEvidenceResponse {
  case_id: string;
  slide_id: string;
  top_tiles: Array<{
    tile_id: string;
    score: number;
    rationale: string;
    bbox?: {
      x: number;
      y: number;
      width: number;
      height: number;
    } | null;
  }>;
  meta: MethodMetadata;
}

export interface CytResponse {
  case_id: string;
  value: number | null;
  available: boolean;
  meta: MethodMetadata;
}

export interface GepResponse {
  case_id: string;
  value: number | null;
  available: boolean;
  meta: MethodMetadata;
}

export interface TideResponse {
  case_id: string;
  value: number | null;
  available: boolean;
  experimental: boolean;
  meta: MethodMetadata;
}

export interface TranscriptomicsEvidenceResponse {
  case_id: string;
  top_genes: Array<{
    symbol: string;
    normalized_count: number;
  }>;
  notes: string[];
  meta: MethodMetadata;
}

export interface TranscriptomicsDegVolcanoPoint {
  gene_symbol: string;
  x: number;
  y: number;
  log2_fc_proxy: number;
  p_value_proxy: number;
  raw_tpm: number;
  reference_z?: number | null;
  direction: "up" | "down" | "neutral";
  significant: boolean;
}

export interface TranscriptomicsDegVolcanoPlotConfig {
  x_axis_label: string;
  y_axis_label: string;
  x_threshold_abs: number;
  y_threshold: number;
  p_value_proxy: true;
  proxy_note: string;
  total_genes_observed: number;
  returned_points: number;
}

export interface TranscriptomicsDegVolcanoResponse {
  case_id: string;
  available: boolean;
  data_source: "artifact" | "modality_result" | "counts_tsv" | "unavailable";
  availability_code:
    | "available"
    | "invalid_case_id"
    | "missing_input"
    | "insufficient_gene_coverage"
    | "precompute_missing"
    | "frozen_reference_unavailable"
    | "evidence_unavailable";
  unavailable_reason?: string | null;
  points: TranscriptomicsDegVolcanoPoint[];
  plot: TranscriptomicsDegVolcanoPlotConfig;
  meta: MethodMetadata;
}

export interface TranscriptomicsMaPlotPoint {
  gene_symbol: string;
  mean_expr_log2: number;
  log2_fc: number;
  significant: boolean;
}

export interface TranscriptomicsSignatureScoreBar {
  label: string;
  value: number | null;
  available: boolean;
}

export interface TranscriptomicsHeatmapRow {
  label: string;
  values: number[];
}

export interface TranscriptomicsExpressionHeatmap {
  gene_symbols: string[];
  rows: TranscriptomicsHeatmapRow[];
  available: boolean;
}

export interface TranscriptomicsRawExpressionMatrixRow {
  gene_symbol: string;
  raw_value: number;
  normalized_log2: number;
  rank: number;
}

export interface TranscriptomicsRawExpressionMatrixPreview {
  available: boolean;
  data_source: "artifact" | "modality_result" | "counts_tsv" | "unavailable";
  unavailable_reason?: string | null;
  total_genes_observed: number;
  returned_rows: number;
  preview_limit: number;
  truncated: boolean;
  rows: TranscriptomicsRawExpressionMatrixRow[];
}

export interface TranscriptomicsPlotsResponse {
  case_id: string;
  available: boolean;
  volcano: TranscriptomicsDegVolcanoResponse | null;
  ma_plot: TranscriptomicsMaPlotPoint[];
  top_genes_bar: Array<{ symbol: string; normalized_count: number; raw_tpm?: number | null }>;
  signature_scores: TranscriptomicsSignatureScoreBar[];
  expression_heatmap: TranscriptomicsExpressionHeatmap;
  raw_matrix_preview: TranscriptomicsRawExpressionMatrixPreview;
  meta: MethodMetadata;
}

export interface ClinicalPatientSummaryResponse {
  case_id: string;
  stage: string | null;
  smoking_status: string | null;
  age_at_diagnosis: number | null;
  diagnosis: string | null;
  report_highlights: string[];
  meta: MethodMetadata;
}

export interface ClinicalEligibilityResponse {
  case_id: string;
  eligible_trials: number;
  rationale: string[];
  meta: MethodMetadata;
}

export interface ClinicalSurvivalBaselineResponse {
  case_id: string;
  risk_group: "low" | "intermediate" | "high" | null;
  baseline_months: number | null;
  confidence_interval: [number, number] | null;
  meta: MethodMetadata;
}

export interface KMStratum {
  label: string;
  time_points: number[];
  survival_rates: number[];
  n_at_risk: number[];
  n_events: number;
  n_total: number;
  median_survival_months: number | null;
}

export interface ClinicalSurvivalResponse {
  case_id: string;
  survival_prob_1yr: number | null;
  survival_prob_2yr: number | null;
  survival_prob_5yr: number | null;
  ci_1yr: [number, number] | null;
  ci_5yr: [number, number] | null;
  median_survival_months: number | null;
  patient_score_tier: "high" | "intermediate" | "low" | null;
  km_strata: KMStratum[];
  cox_features_used: string[];
  concordance_index: number | null;
  model_version: string;
  available: boolean;
  meta: MethodMetadata;
}

export interface ClinicalSurvivalMlpResponse {
  case_id: string;
  available: boolean;
  horizon_years: number | null;
  probability: number | null;
  predicted_class: number | null;
  data_source: string;
  unavailable_reason: string | null;
  error_code?: string | null;
  meta: MethodMetadata;
}

export interface ClinicalTrialMatchItem {
  title: string;
  nct_id: string;
  status: string;
  phase: string | null;
  match_score: number;
  match_reasons: string[];
  rationale: string;
  study_url: string;
}

export interface ClinicalTrialMatchResponse {
  case_id: string;
  available: boolean;
  trials: ClinicalTrialMatchItem[];
  data_source: "artifact" | "modality_result" | "clinical_xml" | "case_metadata" | "unavailable";
  unavailable_reason: string | null;
  query_terms: string[];
  meta: MethodMetadata;
}

export interface FusionScoreResponse {
  case_id: string;
  provisional_score: number;
  refined_score: number | null;
  delta: number | null;
  confidence_interval: [number, number];
  missing_modalities: UploadModality[];
  // backend-native fields (optional in UI contract)
  requested_mode?: "provisional" | "refined";
  mode_used?: "provisional" | "refined";
  rna_requested?: boolean;
  rna_applied?: boolean;
  delta_score?: number;
  provisional_ci?: { lower: number; upper: number };
  refined_ci?: { lower: number; upper: number };
  meta: MethodMetadata;
}

export interface FusionAttributionResponse {
  case_id: string;
  contributions: Array<{
    modality: "pathology" | "transcriptomics" | "clinical";
    contribution: number;
  }>;
  // backend-native modalities payload (optional)
  modalities?: Array<{
    modality: "pathology" | "transcriptomics" | "clinical";
    contribution_percent: number;
    available: boolean;
  }>;
  meta: MethodMetadata;
}

export interface FusionSimilarCasesResponse {
  case_id: string;
  similar_cases: Array<{
    case_id: string;
    distance: number;
    note: string;
  }>;
  // backend-native neighbors payload (optional)
  neighbors?: Array<{
    case_id: string;
    similarity: number;
    rationale: string;
    score: number;
    delta_vs_index: number;
  }>;
  meta: MethodMetadata;
}

export type IOImmuneTier = "Hot" | "Warm" | "Cold";

export interface IOScoreComponent {
  name: string;
  value: number | null;
  weight: number;
  available: boolean;
  description: string;
}

export interface IOImmuneScoreResponse {
  case_id: string;
  score: number | null;
  tier: IOImmuneTier | null;
  provisional_score: number;
  refined_score: number | null;
  components: IOScoreComponent[];
  rna_available: boolean;
  missing_components: string[];
  meta: MethodMetadata;
}

export interface IOSimilarCase {
  case_id: string;
  similarity: number;
  tier: IOImmuneTier | null;
  score: number | null;
  gep_z: number | null;
  cyt_z: number | null;
  tide_z: number | null;
  til_fraction: number | null;
  age_at_diagnosis: number | null;
  smoking: string | null;
  stage: string | null;
  rationale: string;
}

export interface IOSimilarCasesResponse {
  case_id: string;
  neighbors: IOSimilarCase[];
  feature_space: string[];
  rna_available: boolean;
  cohort_size: number;
  meta: MethodMetadata;
}

export interface AgentQueryRequest {
  case_id: string;
  query: string;
}

export interface AgentContextResponse {
  case_id: string;
  context_for_llm: string;
  fusion_score: number;
  fusion_mode_used: "provisional" | "refined";
  pathology_summary: string;
  clinical_summary: string;
  transcriptomics_summary: string;
  survival_baseline_summary: string;
  similar_cases: Array<{ case_id: string; similarity: number; rationale: string; score?: number; delta_vs_index?: number }>;
  meta: MethodMetadata;
}

export interface AgentQueryResponse {
  case_id: string;
  answer: string;
  citations: Array<{
    panel: string;
    field: string;
    source: string;
  }>;
  acknowledged_missing_modalities: UploadModality[];
  meta: MethodMetadata;
}

export interface CohortCaseSummary {
  case_id: string;
  display_name: string;
  stage: string | null;
  smoking_status: string | null;
  has_pathology: boolean;
  has_transcriptomics: boolean;
  has_clinical: boolean;
}
