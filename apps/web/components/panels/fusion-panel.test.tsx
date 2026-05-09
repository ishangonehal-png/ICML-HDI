import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FusionPanel } from "./fusion-panel";

const meta = {
  method: "fusion-v2",
  version: "2026.03",
  timestamp: "2026-03-08T00:00:00Z",
  proxy_estimate: true as const,
};

afterEach(() => {
  cleanup();
});

describe("FusionPanel", () => {
  it("keeps endpoint metric labels paired with info-eye tooltip context", () => {
    render(
      <FusionPanel
        score={{
          case_id: "TCGA-05-4244",
          provisional_score: 0.56,
          refined_score: 0.63,
          delta: 0.07,
          confidence_interval: [0.52, 0.69],
          missing_modalities: [],
          mode_used: "refined",
          rna_applied: true,
          meta,
        }}
        attribution={{
          case_id: "TCGA-05-4244",
          contributions: [
            { modality: "pathology", contribution: 0.44 },
            { modality: "transcriptomics", contribution: 0.31 },
            { modality: "clinical", contribution: 0.25 },
          ],
          meta,
        }}
        similar={{
          case_id: "TCGA-05-4244",
          similar_cases: [
            {
              case_id: "TCGA-78-7536",
              distance: 0.21,
              note: "Comparable RNA shift with pathology-confirmed hotspot overlap.",
            },
          ],
          meta,
        }}
      />,
    );

    const provisional = screen.getByRole("button", { name: "Fusion panel Provisional score explanation" });
    const refined = screen.getByRole("button", { name: "Fusion panel Refined score explanation" });
    const delta = screen.getByRole("button", { name: "Fusion panel Delta (RNA effect) explanation" });
    const confidenceInterval = screen.getByRole("button", { name: "Fusion panel Confidence interval explanation" });
    const confidenceIntervalEndpoint = screen.getByRole("button", {
      name: "Fusion panel confidence interval endpoint semantics",
    });
    const attribution = screen.getByRole("button", { name: "Fusion panel modality attribution bars explanation" });
    const similarDistance = screen.getByRole("button", {
      name: "Fusion panel similar patient distance explanation",
    });

    expect(provisional).toBeInTheDocument();
    expect(refined).toBeInTheDocument();
    expect(delta).toBeInTheDocument();
    expect(confidenceInterval).toBeInTheDocument();
    expect(confidenceIntervalEndpoint).toBeInTheDocument();
    expect(attribution).toBeInTheDocument();
    expect(similarDistance).toBeInTheDocument();

    fireEvent.focus(delta);
    expect(screen.getByText(/Delta quantifies the change between provisional and refined estimates/i)).toBeInTheDocument();
    expect(delta).toHaveAttribute("aria-expanded", "true");
  });

  it("renders confidence interval endpoint source line and tooltip trigger when CI is available", () => {
    render(
      <FusionPanel
        score={{
          case_id: "TCGA-05-4244",
          provisional_score: 0.56,
          refined_score: 0.63,
          delta: 0.07,
          confidence_interval: [0.49, 0.64],
          refined_ci: { lower: 0.53, upper: 0.7 },
          provisional_ci: { lower: 0.45, upper: 0.62 },
          missing_modalities: [],
          mode_used: "refined",
          rna_applied: true,
          meta,
        }}
        attribution={{
          case_id: "TCGA-05-4244",
          contributions: [
            { modality: "pathology", contribution: 0.44 },
            { modality: "transcriptomics", contribution: 0.31 },
            { modality: "clinical", contribution: 0.25 },
          ],
          meta,
        }}
        similar={{
          case_id: "TCGA-05-4244",
          similar_cases: [],
          meta,
        }}
      />,
    );

    expect(screen.getByText("53% – 70%")).toBeInTheDocument();
    expect(screen.getByText("Endpoint: refined_ci (RNA-applied mode)")).toBeInTheDocument();

    const ciSemantics = screen.getByRole("button", {
      name: "Fusion panel confidence interval endpoint semantics",
    });
    fireEvent.focus(ciSemantics);

    expect(screen.getByText(/Endpoint semantics clarify which interval source is shown/i)).toBeInTheDocument();
  });

  it("renders explicit null-state messaging when no similar cases are returned", () => {
    render(
      <FusionPanel
        score={{
          case_id: "TCGA-05-4244",
          provisional_score: 0.56,
          refined_score: 0.63,
          delta: 0.07,
          confidence_interval: [0.49, 0.64],
          refined_ci: { lower: 0.53, upper: 0.7 },
          provisional_ci: { lower: 0.45, upper: 0.62 },
          missing_modalities: [],
          mode_used: "refined",
          rna_applied: true,
          meta,
        }}
        attribution={{
          case_id: "TCGA-05-4244",
          contributions: [
            { modality: "pathology", contribution: 0.44 },
            { modality: "transcriptomics", contribution: 0.31 },
            { modality: "clinical", contribution: 0.25 },
          ],
          meta,
        }}
        similar={{
          case_id: "TCGA-05-4244",
          similar_cases: [],
          meta,
        }}
      />,
    );

    expect(screen.getByText("No similar patient matches returned for this run.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fusion panel similar patient retrieval explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fusion panel similar patient distance explanation" })).toBeInTheDocument();
  });

  it("shows clear fallback text when fusion confidence interval is unavailable", () => {
    render(
      <FusionPanel
        score={{
          case_id: "TCGA-44-2656",
          provisional_score: 0.51,
          refined_score: null,
          delta: null,
          confidence_interval: null as unknown as [number, number],
          missing_modalities: ["transcriptomics"],
          mode_used: "provisional",
          rna_applied: false,
          meta,
        }}
        attribution={{
          case_id: "TCGA-44-2656",
          contributions: [
            { modality: "pathology", contribution: 0.58 },
            { modality: "clinical", contribution: 0.42 },
            { modality: "transcriptomics", contribution: 0 },
          ],
          meta,
        }}
        similar={{
          case_id: "TCGA-44-2656",
          similar_cases: [],
          meta,
        }}
      />,
    );

    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Endpoint unavailable — provisional interval not returned")).toBeInTheDocument();

    const ciSemantics = screen.getByRole("button", {
      name: "Fusion panel confidence interval endpoint semantics",
    });
    fireEvent.focus(ciSemantics);

    expect(screen.getByText(/no confidence-interval payload was returned/i)).toBeInTheDocument();
  });

  it("falls back to active confidence_interval when endpoint-specific CI payload is invalid", () => {
    render(
      <FusionPanel
        score={{
          case_id: "TCGA-12-7010",
          provisional_score: 0.54,
          refined_score: 0.6,
          delta: 0.06,
          confidence_interval: [0.52, 0.69],
          refined_ci: { lower: Number.NaN, upper: 0.69 },
          missing_modalities: [],
          mode_used: "refined",
          rna_applied: true,
          meta,
        }}
        attribution={{
          case_id: "TCGA-12-7010",
          contributions: [
            { modality: "pathology", contribution: 0.4 },
            { modality: "transcriptomics", contribution: 0.35 },
            { modality: "clinical", contribution: 0.25 },
          ],
          meta,
        }}
        similar={{
          case_id: "TCGA-12-7010",
          similar_cases: [],
          meta,
        }}
      />,
    );

    expect(screen.getByText("52% – 69%")).toBeInTheDocument();
    expect(screen.getByText("Endpoint: confidence_interval (refined mode summary)")).toBeInTheDocument();
    expect(screen.queryByText(/NaN%/i)).not.toBeInTheDocument();
  });
});
