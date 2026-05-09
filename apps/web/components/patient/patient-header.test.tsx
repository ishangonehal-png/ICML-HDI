import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PatientHeader } from "./patient-header";

describe("PatientHeader", () => {
  it("removes trial match card from top summary and keeps IO/similar summaries", () => {
    render(
      <PatientHeader
        caseSummary={{
          case_id: "TCGA-49-4512",
          display_name: "TCGA-49-4512",
          stage: "Stage II",
          smoking_status: "Former smoker",
          has_pathology: true,
          has_transcriptomics: true,
          has_clinical: true,
        }}
        clinicalSummary={{
          case_id: "TCGA-49-4512",
          stage: "Stage II",
          smoking_status: "Former smoker",
          age_at_diagnosis: 62,
          diagnosis: "Lung adenocarcinoma",
          report_highlights: [],
          meta: {
            method: "clinical-extract-v1",
            version: "2026.03",
            timestamp: "2026-03-07T18:00:00.000Z",
            proxy_estimate: true,
          },
        }}
        ioImmuneScore={{
          case_id: "TCGA-49-4512",
          score: 0.57,
          tier: "Warm",
          provisional_score: 0.42,
          refined_score: 0.57,
          components: [],
          rna_available: true,
          missing_components: [],
          meta: {
            method: "io-immune-score-v1",
            version: "2026.03",
            timestamp: "2026-03-07T18:04:00.000Z",
            proxy_estimate: true,
          },
        }}
      />,
    );

    expect(screen.getByText("TCGA-49-4512")).toBeInTheDocument();
    expect(screen.getByText("Research-only summary")).toBeInTheDocument();

    expect(screen.queryByText("Trial matches")).not.toBeInTheDocument();
    expect(screen.getByText("IO readiness")).toBeInTheDocument();
    expect(screen.getByText("Most similar patients")).toBeInTheDocument();
    expect(screen.getByText(/No similar cohort match/)).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: "Patient header diagnosis, stage, and smoking status context" }),
    ).toBeInTheDocument();
  });
});
