import {
  apiClient,
  type ClinicalEligibilityResponse,
  type ClinicalPatientSummaryResponse,
  type ClinicalSurvivalBaselineResponse,
  type ClinicalSurvivalResponse,
  type ClinicalSurvivalMlpResponse,
  type CohortCaseSummary,
  type CytResponse,
  type GepResponse,
  type IOImmuneScoreResponse,
  type IOSimilarCasesResponse,
  type PathologyEvidenceResponse,
  type PathologyHeatmapResponse,
  type PathologyTissueCompositionResponse,
  type TideResponse,
  type TranscriptomicsDegVolcanoResponse,
  type TranscriptomicsEvidenceResponse,
  type TranscriptomicsPlotsResponse,
} from "@/lib/api-client";

export interface PatientWorkspaceBootstrapData {
  cases: CohortCaseSummary[];
  selectedCase: CohortCaseSummary;
}

export interface PathologyPanelData {
  tissue: PathologyTissueCompositionResponse | null;
  heatmap: PathologyHeatmapResponse | null;
  evidence: PathologyEvidenceResponse | null;
}

export interface TranscriptomicsPanelData {
  cyt: CytResponse;
  gep: GepResponse;
  tide: TideResponse;
  evidence: TranscriptomicsEvidenceResponse;
  degVolcano: TranscriptomicsDegVolcanoResponse;
  plots: TranscriptomicsPlotsResponse | null;
}

export interface ClinicalPanelData {
  summary: ClinicalPatientSummaryResponse | null;
  eligibility: ClinicalEligibilityResponse | null;
  survival: ClinicalSurvivalBaselineResponse | null;
  survivalFull: ClinicalSurvivalResponse | null;
  survivalMlp: ClinicalSurvivalMlpResponse;
}

export interface IOImmunePanelData {
  score: IOImmuneScoreResponse;
  similarCases: IOSimilarCasesResponse | null;
  similarCasesError?: string;
}

export type PatientWorkspaceSectionStatus = "loading" | "ready" | "error";

export interface PatientWorkspaceSectionState<TData> {
  status: PatientWorkspaceSectionStatus;
  data: TData | null;
  errorMessage?: string;
}

export async function loadPatientWorkspaceBootstrap(
  caseId: string,
): Promise<PatientWorkspaceBootstrapData> {
  const cases = await apiClient.listCohortCases();
  const selectedCase =
    cases.find((entry) => entry.case_id === caseId) ??
    cases[0] ??
    apiClient.getDefaultCase();

  return {
    cases,
    selectedCase,
  };
}

export async function loadPathologyPanelData(caseId: string): Promise<PathologyPanelData> {
  const [tissue, heatmap, evidence] = await Promise.all([
    apiClient.getPathologyTissueComposition(caseId),
    apiClient.getPathologyHeatmap(caseId),
    apiClient.getPathologyEvidence(caseId),
  ]);

  return {
    tissue,
    heatmap,
    evidence,
  };
}

export async function loadTranscriptomicsPanelData(
  caseId: string,
): Promise<TranscriptomicsPanelData> {
  const [cyt, gep, tide, evidence, degVolcano, plots] = await Promise.all([
    apiClient.getCyt(caseId),
    apiClient.getGep(caseId),
    apiClient.getTide(caseId),
    apiClient.getTranscriptomicEvidence(caseId),
    apiClient.getTranscriptomicDegVolcano(caseId),
    apiClient.getTranscriptomicsPlots(caseId),
  ]);

  return {
    cyt,
    gep,
    tide,
    evidence,
    degVolcano,
    plots,
  };
}

export async function loadClinicalPanelData(caseId: string): Promise<ClinicalPanelData> {
  const [summary, eligibility, survival, survivalFull, survivalMlp] = await Promise.all([
    apiClient.getClinicalPatientSummary(caseId),
    apiClient.getClinicalEligibility(caseId),
    apiClient.getClinicalSurvivalBaseline(caseId),
    apiClient.getClinicalSurvival(caseId),
    apiClient.getClinicalSurvivalMlp(caseId),
  ]);

  return {
    summary,
    eligibility,
    survival,
    survivalFull,
    survivalMlp,
  };
}

export async function loadIOImmunePanelData(caseId: string): Promise<IOImmunePanelData> {
  const score = await apiClient.getIOImmuneScore(caseId);

  let similarCases: IOSimilarCasesResponse | null = null;
  let similarCasesError: string | undefined;
  try {
    similarCases = await apiClient.getIOSimilarCases(caseId);
  } catch (error) {
    similarCasesError =
      error instanceof Error && error.message.trim().length > 0
        ? error.message
        : "Unable to load similar patients.";
  }

  return {
    score,
    similarCases,
    similarCasesError,
  };
}
