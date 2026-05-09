import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { getAnalysisJobMock } = vi.hoisted(() => ({
  getAnalysisJobMock: vi.fn().mockResolvedValue({
    job_id: "job_smoke_analysis",
    case_id: "TCGA-ANALYSIS-0001",
    state: "completed",
    created_at: "2026-03-05T20:00:00.000Z",
    updated_at: "2026-03-05T20:01:00.000Z",
    steps: [
      { key: "queue", label: "Queued", status: "completed", detail: "Ready" },
      {
        key: "pathology",
        label: "Pathology",
        status: "completed",
        detail: "Heatmap available",
      },
      {
        key: "clinical",
        label: "Clinical",
        status: "completed",
        detail: "Summary extracted",
      },
    ],
    research_only: true,
  }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: unknown }) => (
    <a href={href} {...props}>
      {children as any}
    </a>
  ),
}));

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    getAnalysisJob: getAnalysisJobMock,
  },
}));

import AnalysisPage from "./page";

describe("/analysis/[job_id] page", () => {
  it("renders analysis status and navigation actions", async () => {
    getAnalysisJobMock.mockResolvedValueOnce({
      job_id: "job_smoke_analysis",
      case_id: "TCGA-ANALYSIS-0001",
      state: "completed",
      created_at: "2026-03-05T20:00:00.000Z",
      updated_at: "2026-03-05T20:01:00.000Z",
      steps: [
        { key: "queue", label: "Queued", status: "completed", detail: "Ready" },
        {
          key: "pathology",
          label: "Pathology",
          status: "completed",
          detail: "Heatmap available",
        },
        {
          key: "clinical",
          label: "Clinical",
          status: "completed",
          detail: "Summary extracted",
        },
      ],
      research_only: true,
    });

    const page = await AnalysisPage({
      params: Promise.resolve({ job_id: "job_smoke_analysis" }),
      searchParams: Promise.resolve({ case_id: "TCGA-ANALYSIS-0001" }),
    });

    render(page);

    expect(getAnalysisJobMock).toHaveBeenCalledWith(
      "job_smoke_analysis",
      "TCGA-ANALYSIS-0001",
    );
    expect(screen.getByText("Analysis job job_smoke_analysis")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to upload" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open patient workspace" }),
    ).toHaveAttribute("href", "/patient/TCGA-ANALYSIS-0001");
  });

  it("routes failed jobs to upload-based retry without mutating job id", async () => {
    getAnalysisJobMock.mockResolvedValueOnce({
      job_id: "0cc1b9f7-4467-4e4b-bf61-ebbf8ea01d57",
      case_id: "TCGA-ANALYSIS-0002",
      state: "failed",
      created_at: "2026-03-05T20:00:00.000Z",
      updated_at: "2026-03-05T20:03:00.000Z",
      steps: [
        { key: "queue", label: "Queued", status: "completed", detail: "Ready" },
        { key: "fusion", label: "Fusion", status: "failed", detail: "Worker timeout" },
      ],
      errors: ["Fusion worker timeout. Please retry."],
      research_only: true,
    });

    const page = await AnalysisPage({
      params: Promise.resolve({ job_id: "0cc1b9f7-4467-4e4b-bf61-ebbf8ea01d57" }),
      searchParams: Promise.resolve({ case_id: "TCGA-ANALYSIS-0002" }),
    });

    render(page);

    expect(screen.getByText("Error surfaced")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Retry from upload" })).toHaveAttribute(
      "href",
      "/upload?case_id=TCGA-ANALYSIS-0002",
    );
    expect(screen.getByRole("link", { name: "Retry analysis" })).toHaveAttribute(
      "href",
      "/upload?case_id=TCGA-ANALYSIS-0002",
    );
  });
});
