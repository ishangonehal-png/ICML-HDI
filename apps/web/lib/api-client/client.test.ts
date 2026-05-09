import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.fn();

afterEach(() => {
  fetchMock.mockReset();
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
  delete process.env.INTERNAL_API_BASE_URL;
  delete process.env.API_BASE_URL;
  vi.resetModules();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

async function loadClient(options?: {
  externalApiBaseUrl?: string;
  internalApiBaseUrl?: string;
}) {
  process.env.NEXT_PUBLIC_API_BASE_URL =
    options?.externalApiBaseUrl ?? "http://api.example.test";

  if (options?.internalApiBaseUrl) {
    process.env.INTERNAL_API_BASE_URL = options.internalApiBaseUrl;
  }

  const module = await import("./client");
  return module.apiClient;
}

describe("apiClient response coercion", () => {
  it("normalizes upload init response from backend schema", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 201,
      statusText: "Created",
      json: async () => ({
        upload_session_id: "7f769b67-90ef-47f8-b289-c59134b8692e",
        case_id: "TCGA-05-4244",
        cohort: "mvp50",
        status: "initialized",
        metadata: { source: "cohort_select" },
        created_at: "2026-03-05T20:00:00.000Z",
        research_use_only: true,
      }),
    });

    const apiClient = await loadClient();
    const result = await apiClient.initUpload({
      case_id: "TCGA-05-4244",
      source: "cohort_select",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.example.test/v1/uploads/init",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.session_id).toBe("7f769b67-90ef-47f8-b289-c59134b8692e");
    expect(result.accepted_modalities).toEqual([
      "pathology",
      "transcriptomics",
      "clinical",
    ]);
    expect(result.research_only).toBe(true);
  });

  it("maps backend analysis job detail into UI-safe timeline shape", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        job_id: "57df8f9d-1a73-4b15-94a3-f58d69319403",
        case_id: "TCGA-05-4244",
        status: "running",
        requested_modalities: ["pathology", "clinical", "fusion"],
        created_at: "2026-03-05T20:00:00.000Z",
        updated_at: "2026-03-05T20:01:00.000Z",
        events: [
          {
            event_type: "job_started",
            message: "Worker picked up queued job.",
            created_at: "2026-03-05T20:00:15.000Z",
            payload: { worker: "worker-a" },
          },
          {
            event_type: "modality_started",
            message: "Clinical started.",
            created_at: "2026-03-05T20:00:31.000Z",
            payload: { modality: "clinical", status: "running" },
          },
        ],
        modality_results: [
          {
            modality: "pathology",
            payload: {},
            metadata: {},
            created_at: "2026-03-05T20:00:30.000Z",
          },
        ],
        research_use_only: true,
      }),
    });

    const apiClient = await loadClient();
    const result = await apiClient.getAnalysisJob(
      "57df8f9d-1a73-4b15-94a3-f58d69319403",
      "TCGA-05-4244",
    );

    expect(result.state).toBe("running");
    expect(result.steps[0].key).toBe("queue");
    expect(result.steps.some((step) => step.key === "pathology" && step.status === "completed")).toBe(true);
    expect(result.steps.some((step) => step.key === "clinical" && step.status === "running")).toBe(true);
    expect(result.steps.find((step) => step.key === "clinical")?.detail).toContain("Clinical started");
    expect(result.events?.length).toBe(2);
  });

  it("marks queue step failed when job fails before worker start", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        job_id: "1e4a96e9-f9f7-4f1d-b9f0-20755027f8cb",
        case_id: "TCGA-05-4244",
        status: "failed",
        requested_modalities: ["pathology", "transcriptomics", "clinical", "fusion"],
        error_message: "Queue enqueue failed. Worker could not pick up this job. Please retry.",
        created_at: "2026-03-05T20:00:00.000Z",
        updated_at: "2026-03-05T20:01:00.000Z",
        events: [
          {
            event_type: "job_created",
            message: "Analysis job created and queued for asynchronous execution.",
            created_at: "2026-03-05T20:00:05.000Z",
            payload: {},
          },
          {
            event_type: "job_enqueue_failed",
            message: "Analysis queue unavailable while enqueueing job.",
            created_at: "2026-03-05T20:00:06.000Z",
            payload: {},
          },
        ],
        modality_results: [],
      }),
    });

    const apiClient = await loadClient();
    const result = await apiClient.getAnalysisJob("1e4a96e9-f9f7-4f1d-b9f0-20755027f8cb");

    expect(result.state).toBe("failed");
    expect(result.steps[0]).toMatchObject({
      key: "queue",
      status: "failed",
      detail: "Analysis queue unavailable while enqueueing job.",
    });
    expect(result.steps.some((step) => step.key === "pathology" && step.status === "queued")).toBe(true);
  });

  it("accepts backend status field when steps are provided", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        job_id: "a2b3f19d-1b2d-4ea9-b4aa-8b77a0f48779",
        case_id: "TCGA-05-4244",
        status: "completed",
        created_at: "2026-03-05T20:00:00.000Z",
        updated_at: "2026-03-05T20:01:00.000Z",
        steps: [
          { key: "queue", label: "Queued", status: "completed" },
          { key: "pathology", label: "Pathology", status: "completed" },
        ],
      }),
    });

    const apiClient = await loadClient();
    const result = await apiClient.getAnalysisJob("a2b3f19d-1b2d-4ea9-b4aa-8b77a0f48779");

    expect(result.state).toBe("completed");
    expect(result.steps).toHaveLength(2);
  });

  it("does not use mock fallback for createAnalysisJob when backend errors", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      json: async () => ({ detail: "queue unavailable" }),
    });

    const apiClient = await loadClient();

    await expect(
      apiClient.createAnalysisJob({
        case_id: "TCGA-05-4244",
        session_id: "7f769b67-90ef-47f8-b289-c59134b8692e",
      }),
    ).rejects.toThrow("503 Service Unavailable: queue unavailable");
  });

  it("surfaces validation details from backend detail arrays", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: async () => ({
        detail: [
          {
            loc: ["body", "case_id"],
            msg: "field required",
            type: "value_error.missing",
          },
        ],
      }),
    });

    const apiClient = await loadClient();

    await expect(
      apiClient.createAnalysisJob({
        case_id: "TCGA-05-4244",
        session_id: "7f769b67-90ef-47f8-b289-c59134b8692e",
      }),
    ).rejects.toThrow("422 Unprocessable Entity: field required");
  });

  it("falls back to mock payload when backend returns scaffolded stub", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        case_id: "TCGA-05-4244",
        status: "stub",
        message: "endpoint scaffold",
        research_use_only: true,
      }),
    });

    const apiClient = await loadClient();
    const tissue = await apiClient.getPathologyTissueComposition("TCGA-05-4244");

    expect(tissue).not.toBeNull();
    expect(tissue?.fractions.length).toBeGreaterThan(0);
    expect(tissue?.case_id).toBe("TCGA-05-4244");
  });
});
