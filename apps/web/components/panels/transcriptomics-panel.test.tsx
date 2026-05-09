import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TranscriptomicsPanel } from "./transcriptomics-panel";

const meta = {
  method: "rna-signature-v3",
  version: "2026.03",
  timestamp: "2026-03-08T00:00:00Z",
  proxy_estimate: true as const,
};

afterEach(() => {
  cleanup();
});

describe("TranscriptomicsPanel", () => {
  it("keeps transcriptomic endpoint cards and labels wired to info-eye triggers", () => {
    render(
      <TranscriptomicsPanel
        cyt={{ case_id: "TCGA-05-4244", value: 0.62, available: true, meta }}
        gep={{ case_id: "TCGA-05-4244", value: 0.41, available: true, meta }}
        tide={{ case_id: "TCGA-05-4244", value: null, available: false, experimental: true, meta }}
        evidence={{
          case_id: "TCGA-05-4244",
          top_genes: [
            { symbol: "CXCL9", normalized_count: 9.8 },
            { symbol: "GZMB", normalized_count: 7.3 },
          ],
          notes: ["Interferon-γ-like profile remains visible."],
          meta,
        }}
        degVolcano={{
          case_id: "TCGA-05-4244",
          available: false,
          data_source: "unavailable",
          availability_code: "missing_input",
          unavailable_reason: "RNA coverage gate not met for DEG calculation.",
          points: [],
          plot: {
            x_axis_label: "log2 FC",
            y_axis_label: "-log10 p proxy",
            x_threshold_abs: 1,
            y_threshold: 1.3,
            p_value_proxy: true,
            proxy_note: "research-only",
            total_genes_observed: 0,
            returned_points: 0,
          },
          meta,
        }}
      />,
    );

    expect(screen.getByRole("button", { name: "Transcriptomics CYT score explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics GEP score explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics TIDE score explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics TIDE unavailable explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics RNA evidence explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics interpretation notes explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics DEG volcano proxy explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics DEG unavailable explanation" })).toBeInTheDocument();
  });

  it("opens endpoint tooltip copy on focus to guard interaction behavior", () => {
    render(
      <TranscriptomicsPanel
        cyt={{ case_id: "TCGA-05-4244", value: 0.62, available: true, meta }}
        gep={{ case_id: "TCGA-05-4244", value: 0.41, available: true, meta }}
        tide={{ case_id: "TCGA-05-4244", value: 0.33, available: true, experimental: true, meta }}
        evidence={{ case_id: "TCGA-05-4244", top_genes: [], notes: [], meta }}
        degVolcano={{
          case_id: "TCGA-05-4244",
          available: false,
          data_source: "unavailable",
          availability_code: "missing_input",
          unavailable_reason: "DEG unavailable",
          points: [],
          plot: {
            x_axis_label: "log2 FC",
            y_axis_label: "-log10 p proxy",
            x_threshold_abs: 1,
            y_threshold: 1.3,
            p_value_proxy: true,
            proxy_note: "research-only",
            total_genes_observed: 0,
            returned_points: 0,
          },
          meta,
        }}
      />,
    );

    const tideInfo = screen.getByRole("button", { name: "Transcriptomics TIDE score explanation" });
    expect(tideInfo).toHaveAttribute("aria-expanded", "false");

    fireEvent.focus(tideInfo);

    expect(tideInfo).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/immune dysfunction and exclusion patterns/i)).toBeInTheDocument();
  });

  it("keeps unavailable CYT/GEP/TIDE cards visible with helper tooltips", () => {
    render(
      <TranscriptomicsPanel
        cyt={{ case_id: "TCGA-05-4244", value: null, available: false, meta }}
        gep={{ case_id: "TCGA-05-4244", value: null, available: false, meta }}
        tide={{ case_id: "TCGA-05-4244", value: null, available: false, experimental: true, meta }}
        evidence={{ case_id: "TCGA-05-4244", top_genes: [], notes: [], meta }}
        degVolcano={{
          case_id: "TCGA-05-4244",
          available: false,
          data_source: "unavailable",
          availability_code: "missing_input",
          unavailable_reason: "RNA coverage gate not met for DEG calculation.",
          points: [],
          plot: {
            x_axis_label: "log2 FC",
            y_axis_label: "-log10 p proxy",
            x_threshold_abs: 1,
            y_threshold: 1.3,
            p_value_proxy: true,
            proxy_note: "research-only",
            total_genes_observed: 0,
            returned_points: 0,
          },
          meta,
        }}
      />,
    );

    expect(screen.getAllByText("Not available for this case")).toHaveLength(3);
    expect(screen.getAllByText("N/A")).toHaveLength(3);

    const cytUnavailableInfo = screen.getByRole("button", { name: "Transcriptomics CYT unavailable explanation" });
    const gepUnavailableInfo = screen.getByRole("button", { name: "Transcriptomics GEP unavailable explanation" });
    const tideUnavailableInfo = screen.getByRole("button", { name: "Transcriptomics TIDE unavailable explanation" });

    expect(cytUnavailableInfo).toBeInTheDocument();
    expect(gepUnavailableInfo).toBeInTheDocument();
    expect(tideUnavailableInfo).toBeInTheDocument();

    fireEvent.focus(cytUnavailableInfo);
    expect(cytUnavailableInfo).toHaveAttribute("aria-expanded", "true");
    expect(document.querySelector('[role="tooltip"][aria-hidden="false"]')).toHaveTextContent(/endpoint could not be computed/i);

    const degUnavailableInfo = screen.getByRole("button", { name: "Transcriptomics DEG unavailable explanation" });
    fireEvent.focus(degUnavailableInfo);
    expect(screen.getByText(/DEG visuals can be unavailable/i)).toBeInTheDocument();
  });

  it("shows and opens the missing-modality fallback message tooltip", () => {
    render(
      <TranscriptomicsPanel
        cyt={{ case_id: "TCGA-05-4244", value: null, available: false, meta }}
        gep={{ case_id: "TCGA-05-4244", value: null, available: false, meta }}
        tide={{ case_id: "TCGA-05-4244", value: null, available: false, experimental: true, meta }}
        evidence={{ case_id: "TCGA-05-4244", top_genes: [], notes: [], meta }}
        degVolcano={{
          case_id: "TCGA-05-4244",
          available: false,
          data_source: "unavailable",
          availability_code: "missing_input",
          unavailable_reason: "RNA coverage gate not met for DEG calculation.",
          points: [],
          plot: {
            x_axis_label: "log2 FC",
            y_axis_label: "-log10 p proxy",
            x_threshold_abs: 1,
            y_threshold: 1.3,
            p_value_proxy: true,
            proxy_note: "research-only",
            total_genes_observed: 0,
            returned_points: 0,
          },
          meta,
        }}
      />,
    );

    expect(screen.getByText(/RNA modality missing/i)).toBeInTheDocument();
    const fallbackInfo = screen.getByRole("button", {
      name: "Transcriptomics missing modality fallback explanation",
    });
    expect(fallbackInfo).toHaveAttribute("aria-expanded", "false");

    fireEvent.focus(fallbackInfo);

    expect(fallbackInfo).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/panel stays visible even when RNA is missing/i)).toBeInTheDocument();
  });

  it("does not render RNA-missing fallback when RNA evidence exists but signature cards are unavailable", () => {
    render(
      <TranscriptomicsPanel
        cyt={{ case_id: "TCGA-05-4244", value: null, available: false, meta }}
        gep={{ case_id: "TCGA-05-4244", value: null, available: false, meta }}
        tide={{ case_id: "TCGA-05-4244", value: null, available: false, experimental: true, meta }}
        evidence={{
          case_id: "TCGA-05-4244",
          top_genes: [{ symbol: "CXCL9", normalized_count: 9.8 }],
          notes: ["Evidence loaded from transcriptomics payload."],
          meta,
        }}
        degVolcano={{
          case_id: "TCGA-05-4244",
          available: false,
          data_source: "unavailable",
          availability_code: "evidence_unavailable",
          unavailable_reason: "RNA input exists, but expression rows required for DEG proxy are unavailable.",
          points: [],
          plot: {
            x_axis_label: "log2 FC",
            y_axis_label: "-log10 p proxy",
            x_threshold_abs: 1,
            y_threshold: 1.3,
            p_value_proxy: true,
            proxy_note: "research-only",
            total_genes_observed: 0,
            returned_points: 0,
          },
          meta,
        }}
      />,
    );

    expect(screen.queryByText(/RNA modality missing/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Transcriptomics missing modality fallback explanation" })).not.toBeInTheDocument();
    expect(screen.getByText("CXCL9")).toBeInTheDocument();
  });

  it("covers volcano, MA, and heatmap tooltip labels when transcriptomics plots are available", () => {
    render(
      <TranscriptomicsPanel
        cyt={{ case_id: "TCGA-05-4244", value: 0.62, available: true, meta }}
        gep={{ case_id: "TCGA-05-4244", value: 0.41, available: true, meta }}
        tide={{ case_id: "TCGA-05-4244", value: 0.33, available: true, experimental: true, meta }}
        evidence={{
          case_id: "TCGA-05-4244",
          top_genes: [{ symbol: "CXCL9", normalized_count: 9.8 }],
          notes: ["Interferon-like signal present."],
          meta,
        }}
        degVolcano={{
          case_id: "TCGA-05-4244",
          available: false,
          data_source: "unavailable",
          availability_code: "missing_input",
          unavailable_reason: "DEG unavailable",
          points: [],
          plot: {
            x_axis_label: "log2 FC",
            y_axis_label: "-log10 p proxy",
            x_threshold_abs: 1,
            y_threshold: 1.3,
            p_value_proxy: true,
            proxy_note: "research-only",
            total_genes_observed: 0,
            returned_points: 0,
          },
          meta,
        }}
        plots={{
          case_id: "TCGA-05-4244",
          available: true,
          volcano: {
            case_id: "TCGA-05-4244",
            available: true,
            data_source: "artifact",
            availability_code: "available",
            unavailable_reason: null,
            points: [
              {
                gene_symbol: "CXCL9",
                x: 1.8,
                y: 3.2,
                log2_fc_proxy: 1.8,
                p_value_proxy: 1e-4,
                raw_tpm: 12.4,
                reference_z: 1.2,
                direction: "up",
                significant: true,
              },
              {
                gene_symbol: "MUC1",
                x: -1.4,
                y: 2.3,
                log2_fc_proxy: -1.4,
                p_value_proxy: 5e-3,
                raw_tpm: 4.1,
                reference_z: -0.7,
                direction: "down",
                significant: true,
              },
            ],
            plot: {
              x_axis_label: "log2 FC",
              y_axis_label: "-log10 p proxy",
              x_threshold_abs: 1,
              y_threshold: 1.3,
              p_value_proxy: true,
              proxy_note: "research-only",
              total_genes_observed: 100,
              returned_points: 2,
            },
            meta,
          },
          ma_plot: [
            { gene_symbol: "TP53", mean_expr_log2: 8.3, log2_fc: 1.1, significant: true },
            { gene_symbol: "MUC1", mean_expr_log2: 6.1, log2_fc: -0.8, significant: false },
          ],
          top_genes_bar: [{ symbol: "CXCL9", normalized_count: 9.8, raw_tpm: 12.4 }],
          signature_scores: [
            { label: "CYT", value: 0.62, available: true },
            { label: "GEP", value: 0.41, available: true },
            { label: "TIDE", value: 0.33, available: true },
          ],
          expression_heatmap: {
            available: true,
            gene_symbols: ["CXCL9", "GZMB"],
            rows: [
              { label: "sample-A", values: [1.2, 3.4] },
              { label: "sample-B", values: [2.1, 2.9] },
            ],
          },
          raw_matrix_preview: {
            available: true,
            data_source: "counts_tsv",
            unavailable_reason: null,
            total_genes_observed: 200,
            returned_rows: 3,
            preview_limit: 3,
            truncated: true,
            rows: [
              { gene_symbol: "CXCL9", raw_value: 12.4, normalized_log2: 3.744161, rank: 1 },
              { gene_symbol: "GZMB", raw_value: 8.1, normalized_log2: 3.185867, rank: 2 },
              { gene_symbol: "MUC1", raw_value: 4.1, normalized_log2: 2.350497, rank: 3 },
            ],
          },
          meta,
        }}
      />,
    );

    expect(screen.getByRole("button", { name: "Transcriptomics MA plot interpretation explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics expression heatmap interpretation explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics raw matrix preview explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics volcano plot axes and thresholds explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics returned volcano points summary explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics MA plot axes explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics selected MA plot gene statistics explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics expression heatmap values and range explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcriptomics expression heatmap range semantics explanation" })).toBeInTheDocument();

    const volcanoHeading = screen.getByText("DEG volcano proxy");
    const rawMatrixHeading = screen.getByText("Raw gene expression matrix (preview)");
    const rnaEvidenceHeading = screen.getByText("RNA evidence (top genes)");
    expect(volcanoHeading.compareDocumentPosition(rawMatrixHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(rawMatrixHeading.compareDocumentPosition(rnaEvidenceHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const maPlot = screen.getByRole("img", { name: "Transcriptomics MA plot" });
    const maPoints = maPlot.querySelectorAll("circle");
    expect(maPoints.length).toBeGreaterThan(0);
    fireEvent.click(maPoints[0]);
    expect(screen.getByText(/TP53: mean log₂/i)).toBeInTheDocument();

    const selectedMaInfo = screen.getByRole("button", { name: "Transcriptomics selected MA plot gene statistics explanation" });
    fireEvent.focus(selectedMaInfo);
    expect(screen.getByText(/exact endpoint values for that gene/i)).toBeInTheDocument();

    const volcanoPlot = screen.getByRole("img", { name: "Transcriptomics DEG volcano plot" });
    const volcanoPoints = volcanoPlot.querySelectorAll("circle");
    expect(volcanoPoints.length).toBeGreaterThan(0);
    fireEvent.click(volcanoPoints[0]);
    expect(screen.getByText(/CXCL9 · log2FC proxy/i)).toBeInTheDocument();
  });
});
