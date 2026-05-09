import type {
  AgentContextResponse,
  AgentQueryRequest,
  AgentQueryResponse,
  AnalysisJobCreateRequest,
  AnalysisJobResponse,
  AnalysisStepStatus,
  ClinicalEligibilityResponse,
  ClinicalPatientSummaryResponse,
  ClinicalSurvivalBaselineResponse,
  ClinicalSurvivalMlpResponse,
  ClinicalSurvivalResponse,
  ClinicalTrialMatchResponse,
  KMStratum,
  CohortCaseSummary,
  CytResponse,
  FusionAttributionResponse,
  FusionScoreResponse,
  FusionSimilarCasesResponse,
  GepResponse,
  IOImmuneScoreResponse,
  IOSimilarCasesResponse,
  MethodMetadata,
  PathologyEvidenceResponse,
  PathologyHeatmapResponse,
  PathologyTissueCompositionResponse,
  TideResponse,
  TranscriptomicsDegVolcanoResponse,
  TranscriptomicsEvidenceResponse,
  TranscriptomicsPlotsResponse,
  UploadFilesRequest,
  UploadFilesResponse,
  UploadInitRequest,
  UploadInitResponse,
  UploadModality,
} from "./types";

const nowIso = () => new Date().toISOString();

const meta = (method: string): MethodMetadata => ({
  method,
  version: "hackathon-p0",
  timestamp: nowIso(),
  proxy_estimate: true,
});

export const MOCK_CASES: CohortCaseSummary[] = [
  {
    case_id: "TCGA-05-4244",
    display_name: "Hero Case A",
    stage: "Stage IIA",
    smoking_status: "Former smoker",
    has_pathology: true,
    has_transcriptomics: true,
    has_clinical: true,
  },
  {
    case_id: "TCGA-49-4488",
    display_name: "Hero Case B",
    stage: "Stage IIIB",
    smoking_status: "Current smoker",
    has_pathology: true,
    has_transcriptomics: true,
    has_clinical: true,
  },
  {
    case_id: "TCGA-44-2656",
    display_name: "Hero Case C (No RNA)",
    stage: "Stage IB",
    smoking_status: "Never smoker",
    has_pathology: true,
    has_transcriptomics: false,
    has_clinical: true,
  },
];

export const DEFAULT_CASE = MOCK_CASES[0];

export function getCase(caseId?: string): CohortCaseSummary {
  return MOCK_CASES.find((entry) => entry.case_id === caseId) ?? DEFAULT_CASE;
}

export function mockUploadInit(_payload: UploadInitRequest): UploadInitResponse {
  return {
    session_id: `upl_${Date.now()}`,
    accepted_modalities: ["pathology", "transcriptomics", "clinical"],
    research_only: true,
  };
}

export function mockUploadFiles(payload: UploadFilesRequest): UploadFilesResponse {
  return {
    session_id: payload.session_id,
    file_status: payload.files.map((file) => ({
      file_name: file.file_name,
      modality: file.modality,
      status: "accepted",
    })),
  };
}

const analysisSteps = (missingModalities: UploadModality[] = []): AnalysisStepStatus[] => [
  { key: "queue", label: "Queued", status: "completed", detail: "Resources reserved" },
  { key: "pathology", label: "Pathology", status: "completed", detail: "Heatmap + tissue fractions" },
  {
    key: "transcriptomics",
    label: "Transcriptomics",
    status: missingModalities.includes("transcriptomics") ? "completed" : "completed",
    detail: missingModalities.includes("transcriptomics")
      ? "No RNA uploaded — skipped with fallback"
      : "CYT/GEP/TIDE computed",
  },
  { key: "clinical", label: "Clinical", status: "completed", detail: "Summary extraction complete" },
  { key: "fusion", label: "Fusion", status: "completed", detail: "Provisional/refined proxy scores" },
  {
    key: "evidence_packaging",
    label: "Evidence packaging",
    status: "completed",
    detail: "Citations and provenance bundle ready",
  },
];

export function mockCreateAnalysisJob(payload: AnalysisJobCreateRequest): AnalysisJobResponse {
  const selectedCase = getCase(payload.case_id);
  const jobId = `job_${selectedCase.case_id.toLowerCase().replaceAll("-", "_")}`;
  const missingModalities: UploadModality[] = selectedCase.has_transcriptomics ? [] : ["transcriptomics"];

  return {
    job_id: jobId,
    case_id: selectedCase.case_id,
    state: "running",
    created_at: nowIso(),
    updated_at: nowIso(),
    steps: analysisSteps(missingModalities).map((step, idx) =>
      idx < 3 ? step : { ...step, status: "queued", detail: "Pending previous stage" },
    ),
    research_only: true,
  };
}

export function mockGetAnalysisJob(jobId: string, caseId?: string): AnalysisJobResponse {
  const selectedCase = getCase(caseId ?? jobIdToCaseId(jobId));
  const missingModalities: UploadModality[] = selectedCase.has_transcriptomics ? [] : ["transcriptomics"];

  if (jobId.includes("failed")) {
    return {
      job_id: jobId,
      case_id: selectedCase.case_id,
      state: "failed",
      created_at: nowIso(),
      updated_at: nowIso(),
      steps: analysisSteps(missingModalities).map((step) =>
        step.key === "fusion" ? { ...step, status: "failed", detail: "Fusion worker timeout" } : step,
      ),
      errors: ["Fusion worker timeout. Please retry."],
      research_only: true,
    };
  }

  if (jobId.includes("running")) {
    return {
      job_id: jobId,
      case_id: selectedCase.case_id,
      state: "running",
      created_at: nowIso(),
      updated_at: nowIso(),
      steps: analysisSteps(missingModalities).map((step, idx) =>
        idx <= 2 ? step : idx === 3 ? { ...step, status: "running", detail: "Extracting staging fields" } : step,
      ),
      research_only: true,
    };
  }

  return {
    job_id: jobId,
    case_id: selectedCase.case_id,
    state: "completed",
    created_at: nowIso(),
    updated_at: nowIso(),
    steps: analysisSteps(missingModalities),
    research_only: true,
  };
}

function jobIdToCaseId(jobId: string): string {
  const extracted = jobId.replace("job_", "").replaceAll("_", "-").toUpperCase();
  const match = MOCK_CASES.find((item) => extracted.includes(item.case_id));
  return match?.case_id ?? DEFAULT_CASE.case_id;
}

export function mockPathologyTissue(caseId: string): PathologyTissueCompositionResponse | null {
  const selectedCase = getCase(caseId);
  if (!selectedCase.has_pathology) return null;

  return {
    case_id: selectedCase.case_id,
    slide_id: `${selectedCase.case_id}-DX1`,
    fractions: [
      { tissue: "Tumor", fraction: 0.61 },
      { tissue: "Stroma", fraction: 0.24 },
      { tissue: "Necrosis", fraction: 0.08 },
      { tissue: "Lymphocyte-rich", fraction: 0.07 },
    ],
    qc: {
      coverage: 0.93,
      artifact_warning: "Mild pen-mark artifact at peripheral region",
    },
    meta: meta("pathology-tissue-v1"),
  };
}

export function mockPathologyHeatmap(caseId: string): PathologyHeatmapResponse | null {
  const selectedCase = getCase(caseId);
  if (!selectedCase.has_pathology) return null;

  return {
    case_id: selectedCase.case_id,
    slide_id: `${selectedCase.case_id}-DX1`,
    heatmap_uri: "mock://heatmap/region",
    viewport_hint: {
      x: 0.12,
      y: 0.19,
      width: 0.42,
      height: 0.33,
    },
    meta: meta("pathology-heatmap-v1"),
  };
}

export function mockPathologyEvidence(caseId: string): PathologyEvidenceResponse | null {
  const selectedCase = getCase(caseId);
  if (!selectedCase.has_pathology) return null;

  return {
    case_id: selectedCase.case_id,
    slide_id: `${selectedCase.case_id}-DX1`,
    top_tiles: [
      { tile_id: "tile_183", score: 0.87, rationale: "Dense tumor-infiltrating lymphocyte cluster" },
      { tile_id: "tile_204", score: 0.82, rationale: "Immune-rich stroma adjacent to tumor" },
      { tile_id: "tile_097", score: 0.74, rationale: "Necrotic pocket with peri-necrotic inflammation" },
    ],
    meta: meta("pathology-evidence-v1"),
  };
}

export function mockCyt(caseId: string): CytResponse {
  const selectedCase = getCase(caseId);
  return {
    case_id: selectedCase.case_id,
    value: selectedCase.has_transcriptomics ? 0.63 : null,
    available: selectedCase.has_transcriptomics,
    meta: meta("cyt-proxy-v1"),
  };
}

export function mockGep(caseId: string): GepResponse {
  const selectedCase = getCase(caseId);
  return {
    case_id: selectedCase.case_id,
    value: selectedCase.has_transcriptomics ? 0.57 : null,
    available: selectedCase.has_transcriptomics,
    meta: meta("gep18-proxy-v1"),
  };
}

export function mockTide(caseId: string): TideResponse {
  const selectedCase = getCase(caseId);
  return {
    case_id: selectedCase.case_id,
    value: selectedCase.has_transcriptomics ? 0.48 : null,
    available: selectedCase.has_transcriptomics,
    experimental: true,
    meta: meta("tide-proxy-v1"),
  };
}

export function mockTranscriptomicEvidence(caseId: string): TranscriptomicsEvidenceResponse {
  const selectedCase = getCase(caseId);
  if (!selectedCase.has_transcriptomics) {
    return {
      case_id: selectedCase.case_id,
      top_genes: [],
      notes: ["RNA modality missing for this case; transcriptomics evidence skipped."],
      meta: meta("rna-evidence-v1"),
    };
  }

  return {
    case_id: selectedCase.case_id,
    top_genes: [
      { symbol: "GZMA", normalized_count: 10.8 },
      { symbol: "PRF1", normalized_count: 8.9 },
      { symbol: "CXCL9", normalized_count: 7.6 },
      { symbol: "IFNG", normalized_count: 6.4 },
    ],
    notes: [
      "RNA profile suggests inflamed microenvironment signature.",
      "TIDE is experimental and should be interpreted with caution.",
    ],
    meta: meta("rna-evidence-v1"),
  };
}

export function mockTranscriptomicDegVolcano(caseId: string): TranscriptomicsDegVolcanoResponse {
  const selectedCase = getCase(caseId);
  if (!selectedCase.has_transcriptomics) {
    return {
      case_id: selectedCase.case_id,
      available: false,
      data_source: "unavailable",
      availability_code: "missing_input",
      unavailable_reason: "No transcriptomics input detected for this case.",
      points: [],
      plot: {
        x_axis_label: "log2 fold-change proxy",
        y_axis_label: "-log10 p-value proxy",
        x_threshold_abs: 1,
        y_threshold: 1.3,
        p_value_proxy: true,
        proxy_note:
          "Research-only DEG-style proxy from normalized RNA expression; p-values are approximate and not for clinical use.",
        total_genes_observed: 0,
        returned_points: 0,
      },
      meta: meta("transcriptomics-deg-volcano-unavailable-v1"),
    };
  }

  const points = [
    {
      gene_symbol: "CXCL9",
      x: 1.42,
      y: 2.11,
      log2_fc_proxy: 1.42,
      p_value_proxy: 0.0078,
      raw_tpm: 26,
      reference_z: 1.42,
      direction: "up" as const,
      significant: true,
    },
    {
      gene_symbol: "NKG7",
      x: 1.18,
      y: 1.83,
      log2_fc_proxy: 1.18,
      p_value_proxy: 0.0148,
      raw_tpm: 18,
      reference_z: 1.18,
      direction: "up" as const,
      significant: true,
    },
    {
      gene_symbol: "CD276",
      x: -0.84,
      y: 1.04,
      log2_fc_proxy: -0.84,
      p_value_proxy: 0.091,
      raw_tpm: 3.5,
      reference_z: -0.84,
      direction: "neutral" as const,
      significant: false,
    },
    {
      gene_symbol: "PRF1",
      x: 0.63,
      y: 0.72,
      log2_fc_proxy: 0.63,
      p_value_proxy: 0.19,
      raw_tpm: 9,
      reference_z: 0.63,
      direction: "neutral" as const,
      significant: false,
    },
  ];

  return {
    case_id: selectedCase.case_id,
    available: true,
    data_source: "counts_tsv",
    availability_code: "available",
    points,
    plot: {
      x_axis_label: "log2 fold-change proxy",
      y_axis_label: "-log10 p-value proxy",
      x_threshold_abs: 1,
      y_threshold: 1.3,
      p_value_proxy: true,
      proxy_note:
        "Research-only DEG-style proxy from normalized RNA expression; p-values are approximate and not for clinical use.",
      total_genes_observed: points.length,
      returned_points: points.length,
    },
    meta: meta("transcriptomics-deg-volcano-counts_tsv-v1"),
  };
}

export function mockTranscriptomicsPlots(caseId: string): TranscriptomicsPlotsResponse {
  const selectedCase = getCase(caseId);
  const volcano = mockTranscriptomicDegVolcano(caseId);
  const evidence = mockTranscriptomicEvidence(caseId);
  const cyt = mockCyt(caseId);
  const gep = mockGep(caseId);
  const tide = mockTide(caseId);

  if (!selectedCase.has_transcriptomics) {
    return {
      case_id: selectedCase.case_id,
      available: false,
      volcano: null,
      ma_plot: [],
      top_genes_bar: [],
      signature_scores: [
        { label: "CYT", value: null, available: false },
        { label: "GEP", value: null, available: false },
        { label: "TIDE", value: null, available: false },
      ],
      expression_heatmap: { gene_symbols: [], rows: [], available: false },
      raw_matrix_preview: {
        available: false,
        data_source: "unavailable",
        unavailable_reason: "No transcriptomics input detected for this case.",
        total_genes_observed: 0,
        returned_rows: 0,
        preview_limit: 120,
        truncated: false,
        rows: [],
      },
      meta: meta("transcriptomics-plots-v1"),
    };
  }

  const top_genes_bar = evidence.top_genes.map((g) => ({
    symbol: g.symbol,
    normalized_count: g.normalized_count,
    raw_tpm: null as number | null,
  }));
  const ma_plot = [
    { gene_symbol: "CXCL9", mean_expr_log2: 4.2, log2_fc: 1.42, significant: true },
    { gene_symbol: "NKG7", mean_expr_log2: 3.8, log2_fc: 1.18, significant: true },
    { gene_symbol: "PRF1", mean_expr_log2: 3.4, log2_fc: 0.63, significant: false },
  ];
  const rawMatrixRows = [
    { gene_symbol: "CXCL9", raw_value: 26, normalized_log2: 4.754888, rank: 1 },
    { gene_symbol: "CD8A", raw_value: 22, normalized_log2: 4.523562, rank: 2 },
    { gene_symbol: "NKG7", raw_value: 18, normalized_log2: 4.247928, rank: 3 },
    { gene_symbol: "GZMA", raw_value: 14, normalized_log2: 3.906891, rank: 4 },
    { gene_symbol: "PRF1", raw_value: 9, normalized_log2: 3.321928, rank: 5 },
  ];

  return {
    case_id: selectedCase.case_id,
    available: true,
    volcano: volcano.available ? volcano : null,
    ma_plot,
    top_genes_bar,
    signature_scores: [
      { label: "CYT", value: cyt.value, available: cyt.available },
      { label: "GEP", value: gep.value, available: gep.available },
      { label: "TIDE", value: tide.value, available: tide.available },
    ],
    expression_heatmap: {
      gene_symbols: top_genes_bar.map((g) => g.symbol),
      rows: [{ label: selectedCase.case_id, values: top_genes_bar.map((g) => g.normalized_count) }],
      available: true,
    },
    raw_matrix_preview: {
      available: true,
      data_source: "counts_tsv",
      unavailable_reason: null,
      total_genes_observed: 20,
      returned_rows: rawMatrixRows.length,
      preview_limit: rawMatrixRows.length,
      truncated: true,
      rows: rawMatrixRows,
    },
    meta: meta("transcriptomics-plots-v1"),
  };
}

export function mockClinicalPatientSummary(caseId: string): ClinicalPatientSummaryResponse | null {
  const selectedCase = getCase(caseId);
  if (!selectedCase.has_clinical) return null;

  return {
    case_id: selectedCase.case_id,
    stage: selectedCase.stage,
    smoking_status: selectedCase.smoking_status,
    age_at_diagnosis: 64,
    diagnosis: "Lung adenocarcinoma",
    report_highlights: [
      "Primary LUAD with moderately differentiated morphology.",
      "No documented EGFR mutation in provided report excerpt.",
      "Performance status inferred as ECOG 1 from clinical note proxy.",
    ],
    meta: meta("clinical-summary-v1"),
  };
}

export function mockClinicalEligibility(caseId: string): ClinicalEligibilityResponse | null {
  const selectedCase = getCase(caseId);
  if (!selectedCase.has_clinical) return null;

  return {
    case_id: selectedCase.case_id,
    eligible_trials: 2,
    rationale: [
      "Stage and smoking history meet broad IO trial pre-screen criteria.",
      "Eligibility is a heuristic proxy and requires manual confirmation.",
    ],
    meta: meta("clinical-eligibility-v1"),
  };
}

export function mockClinicalSurvivalBaseline(caseId: string): ClinicalSurvivalBaselineResponse | null {
  const selectedCase = getCase(caseId);
  if (!selectedCase.has_clinical) return null;

  return {
    case_id: selectedCase.case_id,
    risk_group: "intermediate",
    baseline_months: 24,
    confidence_interval: [16, 31],
    meta: meta("clinical-survival-v1"),
  };
}

export function mockClinicalSurvival(caseId: string): ClinicalSurvivalResponse | null {
  const selectedCase = getCase(caseId);
  if (!selectedCase.has_clinical) return null;

  const timePoints = [0, 6, 12, 18, 24, 30, 36, 42, 48, 60];

  function mkStratum(label: string, decayRate: number, n: number): KMStratum {
    const survival_rates = timePoints.map((t) => Math.max(0.02, Math.exp(-decayRate * (t / 12))));

    return {
      label,
      time_points: timePoints,
      survival_rates,
      n_at_risk: survival_rates.map((s) => Math.round(s * n)),
      n_events: Math.round(n * (1 - survival_rates[survival_rates.length - 1])),
      n_total: n,
      median_survival_months: Math.round((Math.log(2) / decayRate) * 12),
    };
  }

  const rnaAvailable = selectedCase.has_transcriptomics;

  return {
    case_id: selectedCase.case_id,
    survival_prob_1yr: 0.71,
    survival_prob_2yr: 0.55,
    survival_prob_5yr: 0.28,
    ci_1yr: [0.64, 0.78],
    ci_5yr: [0.2, 0.37],
    median_survival_months: 31,
    patient_score_tier: "intermediate",
    km_strata: [
      mkStratum("Low risk", 0.45, 154),
      mkStratum("Intermediate risk", 0.85, 154),
      mkStratum("High risk", 1.5, 154),
    ],
    cox_features_used: rnaAvailable
      ? ["Stage", "Age", "Smoking", "Pack-years", "CYT", "GEP", "TIDE"]
      : ["Stage", "Age", "Smoking", "Pack-years"],
    concordance_index: rnaAvailable ? 0.71 : 0.64,
    model_version: rnaAvailable ? "cox-ph-rna-v1" : "cox-ph-clinical-v1",
    available: true,
    meta: meta(rnaAvailable ? "cox-ph-rna-v1" : "cox-ph-clinical-v1"),
  };
}

export function mockClinicalSurvivalMlp(caseId: string): ClinicalSurvivalMlpResponse {
  const selectedCase = getCase(caseId);
  const hasPathology = selectedCase.has_pathology;
  const hasRna = selectedCase.has_transcriptomics;
  if (!hasPathology) {
    return {
      case_id: selectedCase.case_id,
      available: false,
      horizon_years: null,
      probability: null,
      predicted_class: null,
      data_source: "survival_mlp",
      unavailable_reason: "No pathology embedding found for this case (required).",
      meta: meta("survival-mlp-rna-metadata"),
    };
  }
  if (!hasRna) {
    return {
      case_id: selectedCase.case_id,
      available: false,
      horizon_years: null,
      probability: null,
      predicted_class: null,
      data_source: "survival_mlp",
      unavailable_reason: "No RNA embedding found for this case.",
      meta: meta("survival-mlp-rna-metadata"),
    };
  }
  return {
    case_id: selectedCase.case_id,
    available: true,
    horizon_years: 2,
    probability: 0.72,
    predicted_class: 1,
    data_source: "survival_mlp",
    unavailable_reason: null,
    meta: meta("survival-mlp-rna-metadata"),
  };
}

export function mockClinicalTrialMatches(caseId: string): ClinicalTrialMatchResponse {
  const selectedCase = getCase(caseId);

  return {
    case_id: selectedCase.case_id,
    available: true,
    trials: [
      {
        title: "Phase 2 checkpoint inhibitor in stage III/IV NSCLC",
        nct_id: "NCT00000001",
        status: "RECRUITING",
        phase: "Phase 2",
        match_score: 10,
        match_reasons: [
          "Condition aligned with lung cancer focus.",
          "Eligibility text references stage III/IV disease.",
          "Smoking-history criterion documented in protocol text.",
        ],
        rationale: "Condition aligned with lung cancer focus.",
        study_url: "https://clinicaltrials.gov/study/NCT00000001",
      },
      {
        title: "Targeted therapy for advanced lung adenocarcinoma",
        nct_id: "NCT00000002",
        status: "NOT_YET_RECRUITING",
        phase: "Phase 3",
        match_score: 8,
        match_reasons: [
          "Adenocarcinoma terminology present in study record.",
          "Currently in recruiting-adjacent status.",
        ],
        rationale: "Adenocarcinoma terminology present in study record.",
        study_url: "https://clinicaltrials.gov/study/NCT00000002",
      },
    ],
    data_source: "modality_result",
    unavailable_reason: null,
    query_terms: ["lung cancer", "stage iii", "former smoker"],
    meta: meta("clinical-trial-matches-v1"),
  };
}

export function mockFusionScore(caseId: string): FusionScoreResponse {
  const selectedCase = getCase(caseId);

  const provisional = 0.58;
  const refined = selectedCase.has_transcriptomics ? 0.67 : null;

  return {
    case_id: selectedCase.case_id,
    provisional_score: provisional,
    refined_score: refined,
    delta: refined !== null ? Number((refined - provisional).toFixed(2)) : null,
    confidence_interval: [0.52, 0.74],
    missing_modalities: selectedCase.has_transcriptomics ? [] : ["transcriptomics"],
    meta: meta("fusion-xgb-v1"),
  };
}

export function mockFusionAttribution(caseId: string): FusionAttributionResponse {
  const selectedCase = getCase(caseId);
  const hasRna = selectedCase.has_transcriptomics;

  return {
    case_id: selectedCase.case_id,
    contributions: [
      { modality: "pathology", contribution: hasRna ? 0.39 : 0.54 },
      { modality: "clinical", contribution: hasRna ? 0.28 : 0.46 },
      { modality: "transcriptomics", contribution: hasRna ? 0.33 : 0 },
    ],
    meta: meta("fusion-shap-v1"),
  };
}

export function mockFusionSimilarCases(caseId: string): FusionSimilarCasesResponse {
  const selectedCase = getCase(caseId);

  return {
    case_id: selectedCase.case_id,
    similar_cases: MOCK_CASES.filter((item) => item.case_id !== selectedCase.case_id).map((item, index) => ({
      case_id: item.case_id,
      distance: Number((0.09 + index * 0.04).toFixed(2)),
      note: item.has_transcriptomics
        ? "RNA-available neighbor with similar pathology profile"
        : "Pathology+clinical-only neighbor",
    })),
    meta: meta("fusion-similarity-faiss-v1"),
  };
}

export function mockIOImmuneScore(caseId: string): IOImmuneScoreResponse {
  const selectedCase = getCase(caseId);
  const hasRna = selectedCase.has_transcriptomics;

  const provisional = 0.54;
  const refined = hasRna ? 0.68 : null;
  const score = refined ?? provisional;
  const tier = score >= 0.65 ? "Hot" : score >= 0.40 ? "Warm" : "Cold";

  return {
    case_id: selectedCase.case_id,
    score,
    tier,
    provisional_score: provisional,
    refined_score: refined,
    components: [
      { name: "TIL fraction", value: 0.07, weight: 0.15, available: true, description: "Lymphocyte-rich fraction from WSI" },
      { name: "GEP", value: hasRna ? 0.64 : null, weight: 0.35, available: hasRna, description: "18-gene IFNγ signature (sigmoid)" },
      { name: "CYT", value: hasRna ? 0.71 : null, weight: 0.25, available: hasRna, description: "Cytolytic activity GZMA×PRF1 (sigmoid)" },
      { name: "TIDE", value: hasRna ? 0.42 : null, weight: 0.20, available: hasRna, description: "Inverse TIDE immune exclusion (sigmoid)" },
      { name: "PD-L1", value: null, weight: 0.05, available: false, description: "PD-L1 TPS fraction (IHC proxy)" },
    ],
    rna_available: hasRna,
    missing_components: hasRna ? ["PD-L1"] : ["GEP", "CYT", "TIDE", "PD-L1"],
    meta: meta("io-immune-score-v1"),
  };
}

export function mockIOSimilarCases(caseId: string): IOSimilarCasesResponse {
  const selectedCase = getCase(caseId);
  const hasRna = selectedCase.has_transcriptomics;

  const mockAges = [61, 68];
  const mockSmoking = ["Former smoker (>15yr)", "Current smoker"];
  const mockTNM = ["T2bN1M0", "T3N2M0"];

  const neighbors = MOCK_CASES.filter((item) => item.case_id !== selectedCase.case_id).map(
    (item, index) => {
      const sim = Number((0.82 - index * 0.09).toFixed(2));
      const tier = index === 0 ? "Hot" : "Warm";
      const score = index === 0 ? 0.71 : 0.55;
      const age = mockAges[index] ?? 65;
      const smoking = mockSmoking[index] ?? null;
      const tnm = mockTNM[index] ?? "";
      const rnaPart = hasRna
        ? `GEP ${index === 0 ? "+0.6" : "+0.3"}σ · CYT ${index === 0 ? "+0.4" : "+0.2"}σ · `
        : "";
      return {
        case_id: item.case_id,
        similarity: sim,
        tier: tier as "Hot" | "Warm" | "Cold",
        score,
        gep_z: hasRna ? Number((0.6 - index * 0.3).toFixed(2)) : null,
        cyt_z: hasRna ? Number((0.4 - index * 0.2).toFixed(2)) : null,
        tide_z: hasRna ? Number((-0.2 + index * 0.1).toFixed(2)) : null,
        til_fraction: Number((0.08 - index * 0.01).toFixed(2)),
        age_at_diagnosis: age,
        smoking,
        stage: item.stage,
        rationale: `${rnaPart}TIL ${index === 0 ? 8 : 7}% · Age ${age}y · ${smoking ?? "Unknown smoking"} · ${tnm}`,
      };
    },
  );

  return {
    case_id: selectedCase.case_id,
    neighbors,
    feature_space: hasRna
      ? ["GEP", "CYT", "TIDE", "TIL", "Tumor%", "Necrosis%", "Age", "Gender", "Smoking", "Pack-years", "Stage", "T", "N", "M", "ECOG"]
      : ["TIL", "Tumor%", "Necrosis%", "Age", "Gender", "Smoking", "Stage", "T", "N", "M"],
    rna_available: hasRna,
    cohort_size: 462,
    meta: meta("io-knn-v1"),
  };
}

export function mockAgentQuery(payload: AgentQueryRequest): AgentQueryResponse {
  const selectedCase = getCase(payload.case_id);
  const missing: UploadModality[] = selectedCase.has_transcriptomics ? [] : ["transcriptomics"];

  return {
    case_id: selectedCase.case_id,
    answer:
      missing.length > 0
        ? "RNA data is not available for this case, so the score remains provisional (pathology + clinical). Evidence still supports an intermediate immune-infiltrated profile."
        : "RNA features (CYT/GEP) increased the refined proxy score versus provisional. Pathology evidence and clinical stage remain consistent with an immune-inflamed profile.",
    citations: [
      { panel: "fusion", field: "delta", source: "v1/fusion/{case_id}/score" },
      { panel: "transcriptomics", field: "CYT/GEP", source: "v1/transcriptomics/{case_id}/cyt|gep" },
      { panel: "pathology", field: "top_tiles", source: "v1/pathology/slides/{slide_id}/evidence" },
    ],
    acknowledged_missing_modalities: missing,
    meta: meta("agent-grounded-v1"),
  };
}

export function mockAgentContext(caseId: string): AgentContextResponse {
  const selectedCase = getCase(caseId);
  const ctx = `Case: ${selectedCase.case_id}. Fusion score (provisional): 0.62. Pathology: Tumor (45%), Stroma (38%); top evidence tile score 0.71. Clinical: ${selectedCase.stage ?? "N/A"}, ${selectedCase.smoking_status ?? "N/A"}. Transcriptomics: CYT=0.82, GEP=0.61, TIDE=0.44; contribution 28%. Survival: Risk group intermediate; baseline 42 mo. Similar cases: TCGA-49-4488 (similarity=0.89); TCGA-44-2656 (similarity=0.76). Research-only proxy; not for clinical use.`;
  return {
    case_id: selectedCase.case_id,
    context_for_llm: ctx,
    fusion_score: 0.62,
    fusion_mode_used: "provisional",
    pathology_summary: "Tumor (45%), Stroma (38%); top evidence tile score 0.71",
    clinical_summary: `${selectedCase.stage ?? "N/A"}, ${selectedCase.smoking_status ?? "N/A"}.`,
    transcriptomics_summary: "CYT=0.82, GEP=0.61, TIDE=0.44; contribution 28%.",
    survival_baseline_summary: "Risk group intermediate; baseline 42 mo (CI 24-60 mo).",
    similar_cases: [
      { case_id: "TCGA-49-4488", similarity: 0.89, rationale: "Score delta +0.05; closest in pathology.", score: 0.67, delta_vs_index: 0.05 },
      { case_id: "TCGA-44-2656", similarity: 0.76, rationale: "Score delta -0.12; closest in clinical.", score: 0.50, delta_vs_index: -0.12 },
    ],
    meta: meta("agent-context-v1"),
  };
}
