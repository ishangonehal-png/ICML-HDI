import {
  DEFAULT_CASE,
  MOCK_CASES,
  getCase,
  mockAgentQuery,
  mockAgentContext,
  mockClinicalEligibility,
  mockClinicalPatientSummary,
  mockClinicalSurvival,
  mockClinicalSurvivalBaseline,
  mockClinicalSurvivalMlp,
  mockClinicalTrialMatches,
  mockCreateAnalysisJob,
  mockCyt,
  mockFusionAttribution,
  mockFusionScore,
  mockFusionSimilarCases,
  mockGep,
  mockGetAnalysisJob,
  mockIOImmuneScore,
  mockIOSimilarCases,
  mockPathologyEvidence,
  mockPathologyHeatmap,
  mockPathologyTissue,
  mockTide,
  mockTranscriptomicDegVolcano,
  mockTranscriptomicEvidence,
  mockTranscriptomicsPlots,
  mockUploadFiles,
  mockUploadInit,
} from "./mock-data";
import type {
  AgentContextResponse,
  AgentQueryRequest,
  AgentQueryResponse,
  AnalysisJobCreateRequest,
  AnalysisJobEvent,
  AnalysisJobResponse,
  AnalysisStepKey,
  AnalysisStepStatus,
  ClinicalEligibilityResponse,
  ClinicalPatientSummaryResponse,
  ClinicalSurvivalBaselineResponse,
  ClinicalSurvivalMlpResponse,
  ClinicalSurvivalResponse,
  ClinicalTrialMatchResponse,
  CohortCaseSummary,
  CytResponse,
  FusionAttributionResponse,
  FusionScoreResponse,
  FusionSimilarCasesResponse,
  GepResponse,
  IOImmuneScoreResponse,
  IOSimilarCasesResponse,
  JobState,
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

const EXTERNAL_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
const INTERNAL_API_BASE_URL =
  process.env.INTERNAL_API_BASE_URL?.trim() ?? process.env.API_BASE_URL?.trim();
const DISABLE_MOCK_FALLBACK = process.env.NEXT_PUBLIC_DISABLE_MOCK_FALLBACK === "true";

function resolveApiBaseUrl(): string | null {
  const isServerRuntime = typeof window === "undefined";
  const configuredBaseUrl = isServerRuntime
    ? INTERNAL_API_BASE_URL ?? EXTERNAL_API_BASE_URL
    : EXTERNAL_API_BASE_URL;

  if (!configuredBaseUrl) {
    return null;
  }

  return configuredBaseUrl.replace(/\/$/, "");
}

const DEFAULT_UPLOAD_MODALITIES: UploadModality[] = [
  "pathology",
  "transcriptomics",
  "clinical",
];

const ANALYSIS_STEP_LABELS: Record<AnalysisStepKey, string> = {
  queue: "Queued",
  pathology: "Pathology",
  transcriptomics: "Transcriptomics",
  clinical: "Clinical",
  fusion: "Fusion",
  evidence_packaging: "Evidence packaging",
};

const ANALYSIS_CORE_KEYS: Array<Exclude<AnalysisStepKey, "queue" | "evidence_packaging">> = [
  "pathology",
  "transcriptomics",
  "clinical",
  "fusion",
];

function withJsonHeaders(init?: RequestInit): RequestInit {
  return {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  };
}

type ApiParser<T> = (payload: unknown) => T | null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asConfidenceInterval(value: unknown): [number, number] | null {
  if (Array.isArray(value) && value.length >= 2) {
    const lower = asNumber(value[0]);
    const upper = asNumber(value[1]);
    if (lower !== null && upper !== null) {
      return [lower, upper];
    }
  }

  if (isRecord(value)) {
    const lower = asNumber(value.lower);
    const upper = asNumber(value.upper);
    if (lower !== null && upper !== null) {
      return [lower, upper];
    }
  }

  return null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is string => typeof entry === "string");
}

function isUploadModality(value: unknown): value is UploadModality {
  return value === "pathology" || value === "transcriptomics" || value === "clinical";
}

function isAnalysisStepKey(value: unknown): value is AnalysisStepKey {
  return (
    value === "queue" ||
    value === "pathology" ||
    value === "transcriptomics" ||
    value === "clinical" ||
    value === "fusion" ||
    value === "evidence_packaging"
  );
}

function toJobState(value: unknown): JobState {
  if (value === "queued" || value === "running" || value === "completed" || value === "failed") {
    return value;
  }

  if (typeof value === "string") {
    const normalized = value.toLowerCase();
    if (normalized === "done" || normalized === "succeeded" || normalized === "success") {
      return "completed";
    }
    if (normalized === "error") {
      return "failed";
    }
    if (normalized === "pending" || normalized === "created") {
      return "queued";
    }
  }

  return "running";
}

function parseExplicitJobState(value: unknown): JobState | null {
  if (value === "queued" || value === "running" || value === "completed" || value === "failed") {
    return value;
  }
  return null;
}

function parseMethodMetadata(
  value: unknown,
  fallbackMethod: string,
): MethodMetadata {
  if (isRecord(value)) {
    const method = asString(value.method);
    const version = asString(value.version);
    const timestamp = asString(value.timestamp);

    if (method && version && timestamp) {
      return {
        method,
        version,
        timestamp,
        proxy_estimate: true,
      };
    }
  }

  return {
    method: fallbackMethod,
    version: "unknown",
    timestamp: new Date().toISOString(),
    proxy_estimate: true,
  };
}

function extractErrors(payload: Record<string, unknown>): string[] {
  const errors = new Set<string>();

  const list = payload.errors;
  if (Array.isArray(list)) {
    for (const entry of list) {
      if (typeof entry === "string" && entry.trim().length > 0) {
        errors.add(entry);
      }
    }
  }

  const errorMessage = asString(payload.error_message);
  if (errorMessage) {
    errors.add(errorMessage);
  }

  return Array.from(errors);
}

function formatHttpStatus(status: number, statusText: string): string {
  const trimmedStatusText = statusText.trim();
  if (trimmedStatusText.length === 0) {
    return String(status);
  }
  return `${status} ${trimmedStatusText}`;
}

function parseErrorDetail(payload: unknown): string | null {
  if (!isRecord(payload)) {
    return null;
  }

  const directCandidates = [
    asString(payload.detail),
    asString(payload.error_message),
    asString(payload.message),
    asString(payload.error),
  ];

  for (const candidate of directCandidates) {
    if (candidate && candidate.trim().length > 0) {
      return candidate.trim();
    }
  }

  const detailList = payload.detail;
  if (Array.isArray(detailList)) {
    for (const entry of detailList) {
      if (typeof entry === "string" && entry.trim().length > 0) {
        return entry.trim();
      }
      if (isRecord(entry)) {
        const nestedDetail =
          asString(entry.msg) ??
          asString(entry.message) ??
          asString(entry.detail);
        if (nestedDetail && nestedDetail.trim().length > 0) {
          return nestedDetail.trim();
        }
      }
    }
  }

  const errors = extractErrors(payload);
  if (errors.length > 0) {
    return errors[0];
  }

  return null;
}

async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as unknown;
    return parseErrorDetail(payload);
  } catch {
    return null;
  }
}

function parseAnalysisStep(payload: unknown): AnalysisStepStatus | null {
  if (!isRecord(payload)) {
    return null;
  }

  const key = asString(payload.key);
  if (!isAnalysisStepKey(key)) {
    return null;
  }

  const label = asString(payload.label) ?? ANALYSIS_STEP_LABELS[key];
  const status = toJobState(payload.status);
  const detail = asString(payload.detail) ?? undefined;

  return {
    key,
    label,
    status,
    detail,
  };
}

function parseAnalysisEvents(value: unknown): AnalysisJobEvent[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((entry) => {
    if (!isRecord(entry)) {
      return [];
    }

    const eventType = asString(entry.event_type);
    const message = asString(entry.message);
    if (!eventType || !message) {
      return [];
    }

    return [
      {
        event_type: eventType,
        message,
        created_at: asString(entry.created_at) ?? undefined,
        payload: isRecord(entry.payload) ? entry.payload : undefined,
      },
    ];
  });
}

function findLastEventMessage(events: AnalysisJobEvent[], eventType: string): string | undefined {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index]?.event_type === eventType) {
      return events[index].message;
    }
  }
  return undefined;
}

function buildAnalysisStepsFromState(
  state: JobState,
  requestedModalities: string[] = [],
  completedModalities: string[] = [],
  failureDetail?: string,
  events: AnalysisJobEvent[] = [],
): AnalysisStepStatus[] {
  const requestedSet = new Set(
    requestedModalities
      .map((entry) => entry.toLowerCase())
      .filter((entry) => ANALYSIS_CORE_KEYS.includes(entry as (typeof ANALYSIS_CORE_KEYS)[number])),
  );

  const completedSet = new Set(
    completedModalities
      .map((entry) => entry.toLowerCase())
      .filter((entry) => ANALYSIS_CORE_KEYS.includes(entry as (typeof ANALYSIS_CORE_KEYS)[number])),
  );

  const coreKeys =
    requestedSet.size > 0
      ? ANALYSIS_CORE_KEYS.filter((key) => requestedSet.has(key))
      : ANALYSIS_CORE_KEYS;

  const modalityEventMap = new Map<
    (typeof ANALYSIS_CORE_KEYS)[number],
    { status: JobState; detail?: string }
  >();

  for (const event of events) {
    const eventPayload = event.payload;
    if (!isRecord(eventPayload)) {
      continue;
    }

    const modalityRaw = asString(eventPayload.modality)?.toLowerCase();
    if (!modalityRaw || !ANALYSIS_CORE_KEYS.includes(modalityRaw as (typeof ANALYSIS_CORE_KEYS)[number])) {
      continue;
    }

    let statusFromEvent: JobState | null = null;
    if (event.event_type === "modality_started") {
      statusFromEvent = "running";
    } else if (event.event_type === "modality_completed" || event.event_type === "modality_skipped") {
      statusFromEvent = "completed";
    } else if (event.event_type === "modality_failed") {
      statusFromEvent = "failed";
    } else {
      statusFromEvent = parseExplicitJobState(eventPayload.status);
    }

    if (statusFromEvent === null) {
      continue;
    }

    modalityEventMap.set(modalityRaw as (typeof ANALYSIS_CORE_KEYS)[number], {
      status: statusFromEvent,
      detail: event.message,
    });
  }

  const hasJobStarted =
    events.some((entry) => entry.event_type === "job_started") || modalityEventMap.size > 0;
  const queueFailed = state === "failed" && !hasJobStarted;
  const queueStatus: JobState =
    state === "queued" ? "queued" : queueFailed ? "failed" : "completed";

  const queueDetail =
    events
      .filter((entry) =>
        entry.event_type === "job_created" ||
        entry.event_type === "job_cache_hit" ||
        entry.event_type === "job_enqueued" ||
        entry.event_type === "job_enqueue_failed" ||
        entry.event_type === "job_started" ||
        entry.event_type === "job_completed" ||
        entry.event_type === "job_failed",
      )
      .at(-1)?.message ??
    (state === "queued"
      ? "Waiting for worker capacity"
      : queueFailed
        ? failureDetail ?? "Queueing failed before execution"
        : "Resources reserved");

  const steps: AnalysisStepStatus[] = [
    {
      key: "queue",
      label: ANALYSIS_STEP_LABELS.queue,
      status: queueStatus,
      detail: queueDetail,
    },
  ];

  let activeAssigned = false;

  for (const key of coreKeys) {
    let status: JobState;
    const eventState = modalityEventMap.get(key);
    if (completedSet.has(key) || state === "completed") {
      status = "completed";
    } else if (eventState) {
      status = eventState.status;
    } else if (state === "queued") {
      status = "queued";
    } else if (state === "running") {
      status = activeAssigned ? "queued" : "running";
      activeAssigned = true;
    } else if (queueFailed) {
      status = "queued";
    } else {
      status = activeAssigned ? "queued" : "failed";
      activeAssigned = true;
    }

    const detail =
      eventState?.detail ??
      (status === "failed"
        ? failureDetail ?? "Step failed. Retry analysis to continue."
        : status === "running"
          ? "In progress"
          : status === "queued"
            ? "Pending previous stage"
            : undefined);

    steps.push({
      key,
      label: ANALYSIS_STEP_LABELS[key],
      status,
      detail,
    });
  }

  steps.push({
    key: "evidence_packaging",
    label: ANALYSIS_STEP_LABELS.evidence_packaging,
    status:
      state === "completed" ? "completed" : state === "failed" ? "failed" : "queued",
    detail:
      state === "completed"
        ? findLastEventMessage(events, "job_completed") ??
          "Citations and provenance bundle ready"
        : state === "failed"
          ? findLastEventMessage(events, "job_failed") ??
            failureDetail ??
            "Evidence packaging interrupted"
          : "Pending previous stage",
  });

  return steps;
}

function parseCohortCase(payload: unknown): CohortCaseSummary | null {
  if (!isRecord(payload)) {
    return null;
  }

  const caseId = asString(payload.case_id);
  if (!caseId) {
    return null;
  }

  const displayName = asString(payload.display_name) ?? caseId;
  const hasPathology = asBoolean(payload.has_pathology);
  const hasTranscriptomics = asBoolean(payload.has_transcriptomics);
  const hasClinical = asBoolean(payload.has_clinical);

  if (hasPathology === null || hasTranscriptomics === null || hasClinical === null) {
    return null;
  }

  return {
    case_id: caseId,
    display_name: displayName,
    stage: asString(payload.stage),
    smoking_status: asString(payload.smoking_status),
    has_pathology: hasPathology,
    has_transcriptomics: hasTranscriptomics,
    has_clinical: hasClinical,
  };
}

function parseCohortCases(payload: unknown): CohortCaseSummary[] | null {
  if (!Array.isArray(payload)) {
    return null;
  }

  const parsedCases = payload
    .map((entry) => parseCohortCase(entry))
    .filter((entry): entry is CohortCaseSummary => entry !== null);

  if (parsedCases.length === payload.length) {
    return parsedCases;
  }

  return null;
}

function parseUploadInitResponse(payload: unknown): UploadInitResponse | null {
  if (!isRecord(payload)) {
    return null;
  }

  const sessionId = asString(payload.session_id) ?? asString(payload.upload_session_id);
  if (!sessionId) {
    return null;
  }

  const accepted = Array.isArray(payload.accepted_modalities)
    ? payload.accepted_modalities.filter(isUploadModality)
    : [];

  return {
    session_id: sessionId,
    accepted_modalities:
      accepted.length > 0 ? accepted : DEFAULT_UPLOAD_MODALITIES,
    research_only: true,
  };
}

function parseUploadFilesResponse(payload: unknown): UploadFilesResponse | null {
  if (!isRecord(payload)) {
    return null;
  }

  const sessionId = asString(payload.session_id) ?? asString(payload.upload_session_id);
  if (!sessionId) {
    return null;
  }

  const fileStatus = Array.isArray(payload.file_status)
    ? payload.file_status
        .flatMap((entry) => {
          if (!isRecord(entry)) {
            return [];
          }

          const fileName = asString(entry.file_name);
          const modality = entry.modality;
          const status = entry.status;
          const reason = asString(entry.reason) ?? undefined;

          if (
            !fileName ||
            !isUploadModality(modality) ||
            (status !== "accepted" && status !== "rejected")
          ) {
            return [];
          }

          const normalizedStatus: "accepted" | "rejected" =
            status === "accepted" ? "accepted" : "rejected";

          return [
            {
              file_name: fileName,
              modality,
              status: normalizedStatus,
              reason,
            },
          ];
        })
    : [];

  return {
    session_id: sessionId,
    file_status: fileStatus,
  };
}

function parseAnalysisJobResponse(payload: unknown): AnalysisJobResponse | null {
  if (!isRecord(payload)) {
    return null;
  }

  const jobId = asString(payload.job_id);
  const caseId = asString(payload.case_id);

  if (!jobId || !caseId) {
    return null;
  }

  const createdAt = asString(payload.created_at) ?? new Date().toISOString();
  const updatedAt = asString(payload.updated_at) ?? createdAt;
  const errors = extractErrors(payload);
  const events = parseAnalysisEvents(payload.events);

  if (Array.isArray(payload.steps)) {
    const parsedSteps = payload.steps
      .map((step) => parseAnalysisStep(step))
      .filter((step): step is AnalysisStepStatus => step !== null);

    const state = toJobState(payload.state ?? payload.status);
    return {
      job_id: jobId,
      case_id: caseId,
      state,
      created_at: createdAt,
      updated_at: updatedAt,
      steps:
        parsedSteps.length > 0
          ? parsedSteps
          : buildAnalysisStepsFromState(state, asStringArray(payload.requested_modalities)),
      events,
      errors: errors.length > 0 ? errors : undefined,
      research_only: true,
    };
  }

  const state = toJobState(payload.status);
  const requestedModalities = asStringArray(payload.requested_modalities);
  const completedModalities = Array.isArray(payload.modality_results)
    ? payload.modality_results.flatMap((entry) => {
        if (!isRecord(entry)) {
          return [];
        }
        const modality = asString(entry.modality);
        return modality ? [modality] : [];
      })
    : [];

  return {
    job_id: jobId,
    case_id: caseId,
    state,
    created_at: createdAt,
    updated_at: updatedAt,
    steps: buildAnalysisStepsFromState(
      state,
      requestedModalities,
      completedModalities,
      errors[0],
      events,
    ),
    events,
    errors: errors.length > 0 ? errors : undefined,
    research_only: true,
  };
}

function parseAgentQueryResponse(
  payload: unknown,
  fallbackCaseId: string,
): AgentQueryResponse | null {
  if (!isRecord(payload)) {
    return null;
  }

  const answer = asString(payload.answer) ?? asString(payload.message);
  if (!answer) {
    return null;
  }

  const caseId = asString(payload.case_id) ?? fallbackCaseId;

  const citations = Array.isArray(payload.citations)
    ? payload.citations.flatMap((entry) => {
        if (!isRecord(entry)) {
          return [];
        }

        const panel = asString(entry.panel);
        const field = asString(entry.field);
        const source = asString(entry.source);

        if (!panel || !field || !source) {
          return [];
        }

        return [{ panel, field, source }];
      })
    : [];

  const acknowledgedMissingModalities = Array.isArray(payload.acknowledged_missing_modalities)
    ? payload.acknowledged_missing_modalities.filter(isUploadModality)
    : [];

  return {
    case_id: caseId,
    answer,
    citations,
    acknowledged_missing_modalities: acknowledgedMissingModalities,
    meta: parseMethodMetadata(payload.meta, "agent-grounded"),
  };
}

function parseFusionScoreResponse(payload: unknown): FusionScoreResponse | null {
  if (!isRecord(payload)) {
    return null;
  }

  const caseId = asString(payload.case_id);
  const provisionalScore = asNumber(payload.provisional_score);
  const refinedScore = asNumber(payload.refined_score);
  const modeUsedRaw = asString(payload.mode_used);
  const modeUsed =
    modeUsedRaw === "provisional" || modeUsedRaw === "refined"
      ? modeUsedRaw
      : "provisional";

  if (!caseId || provisionalScore === null) {
    return null;
  }

  const provisionalCi = asConfidenceInterval(payload.provisional_ci);
  const refinedCi = asConfidenceInterval(payload.refined_ci);
  const confidenceInterval =
    asConfidenceInterval(payload.confidence_interval) ??
    (modeUsed === "refined" ? refinedCi : provisionalCi) ??
    provisionalCi ??
    refinedCi ??
    [Math.max(0, provisionalScore - 0.1), Math.min(1, provisionalScore + 0.1)];

  const delta =
    asNumber(payload.delta) ??
    asNumber(payload.delta_score) ??
    (refinedScore !== null ? refinedScore - provisionalScore : null);

  const missingModalities = Array.isArray(payload.modalities)
    ? payload.modalities.flatMap((entry) => {
        if (!isRecord(entry)) {
          return [];
        }
        const modality = asString(entry.modality);
        const available = asBoolean(entry.available);
        if (available === false && isUploadModality(modality)) {
          return [modality];
        }
        return [];
      })
    : [];

  return {
    case_id: caseId,
    provisional_score: provisionalScore,
    refined_score: refinedScore,
    delta,
    confidence_interval: confidenceInterval,
    missing_modalities: missingModalities,
    requested_mode:
      asString(payload.requested_mode) === "refined" ? "refined" : "provisional",
    mode_used: modeUsed,
    rna_requested: asBoolean(payload.rna_requested) ?? true,
    rna_applied: asBoolean(payload.rna_applied) ?? false,
    delta_score: asNumber(payload.delta_score) ?? delta ?? 0,
    provisional_ci: provisionalCi
      ? { lower: provisionalCi[0], upper: provisionalCi[1] }
      : undefined,
    refined_ci: refinedCi ? { lower: refinedCi[0], upper: refinedCi[1] } : undefined,
    meta: parseMethodMetadata(payload.meta, "fusion-score"),
  };
}

function parseFusionAttributionResponse(payload: unknown): FusionAttributionResponse | null {
  if (!isRecord(payload)) {
    return null;
  }

  const caseId = asString(payload.case_id);
  if (!caseId) {
    return null;
  }

  const modalities = Array.isArray(payload.modalities)
    ? payload.modalities.flatMap((entry) => {
        if (!isRecord(entry)) {
          return [];
        }
        const modality = asString(entry.modality);
        const contributionPercent = asNumber(entry.contribution_percent);
        const available = asBoolean(entry.available) ?? false;
        if (!isUploadModality(modality) || contributionPercent === null) {
          return [];
        }
        return [
          {
            modality,
            contribution_percent: contributionPercent,
            available,
          },
        ];
      })
    : [];

  const contributions = modalities.map((item) => ({
    modality: item.modality,
    contribution: Math.max(0, Math.min(1, item.contribution_percent / 100)),
  }));

  return {
    case_id: caseId,
    contributions,
    modalities,
    meta: parseMethodMetadata(payload.meta, "fusion-attribution"),
  };
}

function parseFusionSimilarCasesResponse(payload: unknown): FusionSimilarCasesResponse | null {
  if (!isRecord(payload)) {
    return null;
  }

  const caseId = asString(payload.case_id);
  if (!caseId) {
    return null;
  }

  const neighbors = Array.isArray(payload.neighbors)
    ? payload.neighbors.flatMap((entry) => {
        if (!isRecord(entry)) {
          return [];
        }
        const neighborCaseId = asString(entry.case_id);
        const similarity = asNumber(entry.similarity);
        const score = asNumber(entry.score);
        const deltaVsIndex = asNumber(entry.delta_vs_index);
        const rationale = asString(entry.rationale);
        if (
          !neighborCaseId ||
          similarity === null ||
          score === null ||
          deltaVsIndex === null ||
          !rationale
        ) {
          return [];
        }
        return [
          {
            case_id: neighborCaseId,
            similarity,
            rationale,
            score,
            delta_vs_index: deltaVsIndex,
          },
        ];
      })
    : [];

  const similarCases = neighbors.map((neighbor) => ({
    case_id: neighbor.case_id,
    distance: Math.max(0, Math.min(1, 1 - neighbor.similarity)),
    note: neighbor.rationale,
  }));

  return {
    case_id: caseId,
    similar_cases: similarCases,
    neighbors,
    meta: parseMethodMetadata(payload.meta, "fusion-similar-cases"),
  };
}

interface RequestWithMockOptions {
  allowErrorFallback?: boolean;
}

async function requestWithMock<T>(
  path: string,
  init: RequestInit | undefined,
  fallback: () => T,
  parser?: ApiParser<T>,
  options?: RequestWithMockOptions,
): Promise<T> {
  const apiBaseUrl = resolveApiBaseUrl();
  if (!apiBaseUrl) {
    return fallback();
  }

  try {
    const response = await fetch(`${apiBaseUrl}${path}`, withJsonHeaders(init));
    if (!response.ok) {
      const status = formatHttpStatus(response.status, response.statusText);
      const detail = await readErrorDetail(response);
      throw new Error(detail ? `${status}: ${detail}` : status);
    }

    const payload = (await response.json()) as unknown;

    if (isRecord(payload) && payload.status === "stub") {
      throw new Error("Stub payload");
    }

    if (parser) {
      const parsed = parser(payload);
      if (parsed) {
        return parsed;
      }

      throw new Error("Unexpected payload shape");
    }

    return payload as T;
  } catch (error) {
    if (DISABLE_MOCK_FALLBACK || options?.allowErrorFallback === false) {
      throw error;
    }
    return fallback();
  }
}

function slideIdForCase(caseId: string): string {
  return `${caseId}-DX1`;
}

export const apiClient = {
  listCohortCases: async (): Promise<CohortCaseSummary[]> =>
    requestWithMock(
      "/v1/cohort/cases",
      undefined,
      () => MOCK_CASES,
      parseCohortCases,
      { allowErrorFallback: false },
    ),

  initUpload: async (payload: UploadInitRequest): Promise<UploadInitResponse> =>
    requestWithMock(
      "/v1/uploads/init",
      {
        method: "POST",
        body: JSON.stringify({
          case_id: payload.case_id,
          cohort: "mvp50",
          metadata: { source: payload.source },
        }),
      },
      () => mockUploadInit(payload),
      parseUploadInitResponse,
      { allowErrorFallback: false },
    ),

  uploadFiles: async (payload: UploadFilesRequest): Promise<UploadFilesResponse> =>
    requestWithMock(
      "/v1/uploads/files",
      { method: "POST", body: JSON.stringify(payload) },
      () => mockUploadFiles(payload),
      parseUploadFilesResponse,
    ),

  createAnalysisJob: async (payload: AnalysisJobCreateRequest): Promise<AnalysisJobResponse> =>
    requestWithMock(
      "/v1/analysis/jobs",
      {
        method: "POST",
        body: JSON.stringify({
          case_id: payload.case_id,
          upload_session_id: payload.session_id,
          requested_modalities: [
            "pathology",
            "transcriptomics",
            "clinical",
            "fusion",
          ],
          metadata: { source: "web-upload-shell" },
        }),
      },
      () => mockCreateAnalysisJob(payload),
      parseAnalysisJobResponse,
      { allowErrorFallback: false },
    ),

  getAnalysisJob: async (jobId: string, caseId?: string): Promise<AnalysisJobResponse> =>
    requestWithMock(
      `/v1/analysis/jobs/${jobId}`,
      undefined,
      () => mockGetAnalysisJob(jobId, caseId),
      parseAnalysisJobResponse,
      { allowErrorFallback: false },
    ),

  getPathologyTissueComposition: async (
    caseId: string,
    slideId: string = slideIdForCase(caseId),
  ): Promise<PathologyTissueCompositionResponse | null> =>
    requestWithMock(
      `/v1/pathology/slides/${slideId}/tissue-composition`,
      undefined,
      () => mockPathologyTissue(caseId),
    ),

  getPathologyHeatmap: async (
    caseId: string,
    slideId: string = slideIdForCase(caseId),
  ): Promise<PathologyHeatmapResponse | null> =>
    requestWithMock(
      `/v1/pathology/slides/${slideId}/heatmap`,
      undefined,
      () => mockPathologyHeatmap(caseId),
    ),

  getPathologyEvidence: async (
    caseId: string,
    slideId: string = slideIdForCase(caseId),
  ): Promise<PathologyEvidenceResponse | null> =>
    requestWithMock(
      `/v1/pathology/slides/${slideId}/evidence`,
      { method: "POST", body: JSON.stringify({ case_id: caseId }) },
      () => mockPathologyEvidence(caseId),
    ),

  getCyt: async (caseId: string): Promise<CytResponse> =>
    requestWithMock(`/v1/transcriptomics/${caseId}/cyt`, undefined, () => mockCyt(caseId)),

  getGep: async (caseId: string): Promise<GepResponse> =>
    requestWithMock(`/v1/transcriptomics/${caseId}/gep`, undefined, () => mockGep(caseId)),

  getTide: async (caseId: string): Promise<TideResponse> =>
    requestWithMock(`/v1/transcriptomics/${caseId}/tide?experimental=true`, undefined, () =>
      mockTide(caseId),
    ),

  getTranscriptomicEvidence: async (caseId: string): Promise<TranscriptomicsEvidenceResponse> =>
    requestWithMock(
      `/v1/transcriptomics/${caseId}/evidence`,
      { method: "POST", body: JSON.stringify({ case_id: caseId }) },
      () => mockTranscriptomicEvidence(caseId),
    ),

  getTranscriptomicDegVolcano: async (caseId: string): Promise<TranscriptomicsDegVolcanoResponse> =>
    requestWithMock(
      `/v1/transcriptomics/${caseId}/deg-volcano`,
      undefined,
      () => mockTranscriptomicDegVolcano(caseId),
    ),

  getTranscriptomicsPlots: async (caseId: string): Promise<TranscriptomicsPlotsResponse> =>
    requestWithMock(
      `/v1/transcriptomics/${caseId}/plots`,
      undefined,
      () => mockTranscriptomicsPlots(caseId),
    ),

  getClinicalPatientSummary: async (caseId: string): Promise<ClinicalPatientSummaryResponse | null> =>
    requestWithMock(`/v1/clinical/${caseId}/patient-summary`, undefined, () =>
      mockClinicalPatientSummary(caseId),
    ),

  getClinicalEligibility: async (caseId: string): Promise<ClinicalEligibilityResponse | null> =>
    requestWithMock(`/v1/clinical/${caseId}/eligibility`, undefined, () =>
      mockClinicalEligibility(caseId),
    ),

  getClinicalSurvivalBaseline: async (caseId: string): Promise<ClinicalSurvivalBaselineResponse | null> =>
    requestWithMock(`/v1/clinical/${caseId}/survival-baseline`, undefined, () =>
      mockClinicalSurvivalBaseline(caseId),
    ),

  getClinicalSurvival: async (caseId: string): Promise<ClinicalSurvivalResponse | null> =>
    requestWithMock(`/v1/clinical/${caseId}/survival`, undefined, () =>
      mockClinicalSurvival(caseId),
    ),

  getClinicalSurvivalMlp: async (caseId: string): Promise<ClinicalSurvivalMlpResponse> =>
    requestWithMock(`/v1/clinical/${caseId}/survival-mlp`, undefined, () =>
      mockClinicalSurvivalMlp(caseId),
    ),

  getClinicalTrialMatches: async (
    caseId: string,
    options?: { limit?: number; recruitingOnly?: boolean; refresh?: boolean },
  ): Promise<ClinicalTrialMatchResponse> => {
    const params = new URLSearchParams();

    if (typeof options?.limit === "number" && Number.isFinite(options.limit)) {
      params.set("limit", String(Math.max(1, Math.round(options.limit))));
    }

    if (typeof options?.recruitingOnly === "boolean") {
      params.set("recruiting_only", String(options.recruitingOnly));
    }

    if (options?.refresh === true) {
      params.set("refresh", "true");
    }

    const query = params.size > 0 ? `?${params.toString()}` : "";
    return requestWithMock(
      `/v1/clinical/${caseId}/trial-matches${query}`,
      undefined,
      () => mockClinicalTrialMatches(caseId),
      undefined,
      { allowErrorFallback: false },
    );
  },

  getFusionScore: async (caseId: string): Promise<FusionScoreResponse> =>
    requestWithMock(
      `/v1/fusion/${caseId}/score`,
      { method: "POST", body: JSON.stringify({ include_rna: true }) },
      () => mockFusionScore(caseId),
      parseFusionScoreResponse,
    ),

  getFusionAttribution: async (caseId: string): Promise<FusionAttributionResponse> =>
    requestWithMock(
      `/v1/fusion/${caseId}/attribution`,
      undefined,
      () => mockFusionAttribution(caseId),
      parseFusionAttributionResponse,
    ),

  getFusionSimilarCases: async (caseId: string): Promise<FusionSimilarCasesResponse> =>
    requestWithMock(
      `/v1/fusion/${caseId}/similar-cases?limit=1`,
      undefined,
      () => mockFusionSimilarCases(caseId),
      parseFusionSimilarCasesResponse,
    ),

  getIOImmuneScore: async (caseId: string): Promise<IOImmuneScoreResponse> =>
    requestWithMock(`/v1/io-immune/${caseId}/score`, undefined, () =>
      mockIOImmuneScore(caseId),
    ),

  getIOSimilarCases: async (caseId: string): Promise<IOSimilarCasesResponse> =>
    requestWithMock(`/v1/io-immune/${caseId}/similar-cases`, undefined, () =>
      mockIOSimilarCases(caseId),
    ),

  queryAgent: async (payload: AgentQueryRequest): Promise<AgentQueryResponse> =>
    requestWithMock(
      `/v1/agent/query`,
      {
        method: "POST",
        body: JSON.stringify({
          case_id: payload.case_id,
          question: payload.query,
        }),
      },
      () => mockAgentQuery(payload),
      (rawPayload) => parseAgentQueryResponse(rawPayload, payload.case_id),
    ),

  getAgentContext: async (caseId: string): Promise<AgentContextResponse> =>
    requestWithMock(
      `/v1/agent/context/${encodeURIComponent(caseId)}`,
      { method: "GET" },
      () => mockAgentContext(caseId),
    ),

  getDefaultCase: (): CohortCaseSummary => getCase(DEFAULT_CASE.case_id),
};
