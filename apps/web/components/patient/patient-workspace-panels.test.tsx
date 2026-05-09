import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PatientWorkspacePanels } from "./patient-workspace-panels";

vi.mock("@/components/panels/enso-pathology-viewer", () => ({
  EnsoPathologyViewer: ({ slideId }: { slideId: string }) => (
    <div data-testid="mock-enso-viewer">Mock viewer for {slideId}</div>
  ),
}));

const meta = {
  method: "mock-v1",
  version: "2026.03",
  timestamp: "2026-03-08T00:00:00Z",
  proxy_estimate: true as const,
};

describe("PatientWorkspacePanels", () => {
  it("preserves pathology interaction state after switching modality tabs", () => {
    render(
      <PatientWorkspacePanels
        pathologyState={{
          status: "ready",
          data: {
            tissue: {
              case_id: "TCGA-05-4244",
              slide_id: "TCGA-05-4244-DX1",
              fractions: [{ tissue: "Tumor", fraction: 0.68 }],
              qc: { coverage: 0.91 },
              meta,
            },
            heatmap: {
              case_id: "TCGA-05-4244",
              slide_id: "TCGA-05-4244-DX1",
              heatmap_uri: "/mock/heatmap.png",
              slide_preview_uri: "/mock/preview.png",
              viewport_hint: {
                x: 0.12,
                y: 0.2,
                width: 0.3,
                height: 0.25,
              },
              meta,
            },
            evidence: {
              case_id: "TCGA-05-4244",
              slide_id: "TCGA-05-4244-DX1",
              top_tiles: [
                {
                  tile_id: "tile-001",
                  score: 0.81,
                  rationale: "Top tile one",
                  bbox: { x: 0.1, y: 0.2, width: 0.05, height: 0.05 },
                },
                {
                  tile_id: "tile-002",
                  score: 0.74,
                  rationale: "Top tile two",
                  bbox: { x: 0.22, y: 0.3, width: 0.05, height: 0.05 },
                },
              ],
              meta,
            },
          },
        }}
        transcriptomicsState={{
          status: "ready",
          data: {
            cyt: { case_id: "TCGA-05-4244", value: 0.62, available: true, meta },
            gep: { case_id: "TCGA-05-4244", value: 0.41, available: true, meta },
            tide: { case_id: "TCGA-05-4244", value: 0.33, available: true, experimental: true, meta },
            evidence: { case_id: "TCGA-05-4244", top_genes: [], notes: [], meta },
            degVolcano: {
              case_id: "TCGA-05-4244",
              available: false,
              data_source: "unavailable",
              availability_code: "missing_input",
              unavailable_reason: "unavailable",
              points: [],
              plot: {
                x_axis_label: "x",
                y_axis_label: "y",
                x_threshold_abs: 1,
                y_threshold: 1.3,
                p_value_proxy: true,
                proxy_note: "research-only",
                total_genes_observed: 0,
                returned_points: 0,
              },
              meta,
            },
            plots: null,
          },
        }}
        clinicalState={{
          status: "ready",
          data: {
            summary: {
              case_id: "TCGA-05-4244",
              stage: "IIA",
              smoking_status: "Former smoker",
              age_at_diagnosis: 64,
              diagnosis: "Lung adenocarcinoma",
              report_highlights: ["highlight"],
              meta,
            },
            eligibility: null,
            survival: null,
            survivalFull: null,
            survivalMlp: {
              case_id: "TCGA-05-4244",
              available: false,
              horizon_years: null,
              probability: null,
              predicted_class: null,
              data_source: "unavailable",
              unavailable_reason: "Clinical survival MLP unavailable.",
              meta,
            },
          },
        }}
        ioImmuneState={{
          status: "loading",
          data: null,
        }}
      />,
    );

    const tileOne = screen.getByRole("button", { name: /tile-001/i });
    const tileTwo = screen.getByRole("button", { name: /tile-002/i });

    expect(tileOne).toHaveAttribute("aria-pressed", "true");
    expect(tileTwo).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(tileTwo);
    expect(tileTwo).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("tab", { name: /Transcriptomics/i }));
    fireEvent.click(screen.getByRole("tab", { name: /Pathology/i }));

    expect(screen.getByRole("button", { name: /tile-002/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
