import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    listCohortCases: vi.fn().mockResolvedValue([
      {
        case_id: "TCGA-UPLOAD-0001",
        display_name: "Upload Smoke Case",
        stage: "Stage IA",
        smoking_status: "Never smoker",
        has_pathology: true,
        has_transcriptomics: true,
        has_clinical: true,
      },
    ]),
  },
}));

vi.mock("@/components/upload/upload-shell", () => ({
  UploadShell: ({
    cases,
    initialCaseId,
  }: {
    cases: Array<{ case_id: string }>;
    initialCaseId?: string;
  }) => (
    <div data-testid="upload-shell">
      Upload shell rendered for {cases[0]?.case_id} with preselect {initialCaseId ?? "none"}
    </div>
  ),
}));

import UploadPage from "./page";

describe("/upload page", () => {
  it("renders upload shell with fetched cohort cases and selected case query", async () => {
    const page = await UploadPage({
      searchParams: Promise.resolve({ case_id: "TCGA-UPLOAD-0001" }),
    });
    render(page);

    expect(screen.getByTestId("upload-shell")).toHaveTextContent(
      "Upload shell rendered for TCGA-UPLOAD-0001 with preselect TCGA-UPLOAD-0001",
    );
  });
});
