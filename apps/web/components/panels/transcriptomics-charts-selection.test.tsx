import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TranscriptomicsMaPlot } from "./transcriptomics-ma-plot";
import { TranscriptomicsVolcanoPlot } from "./transcriptomics-volcano-plot";

describe("Transcriptomics chart selection", () => {
  it("keeps volcano-point selection scoped to the clicked point when gene symbols repeat", () => {
    render(
      <TranscriptomicsVolcanoPlot
        points={[
          {
            gene_symbol: "DUP",
            x: 1.1,
            y: 1.7,
            log2_fc_proxy: 1.1,
            p_value_proxy: 0.02,
            raw_tpm: 8.1,
            reference_z: 0.2,
            direction: "up",
            significant: true,
          },
          {
            gene_symbol: "DUP",
            x: -1.4,
            y: 2.3,
            log2_fc_proxy: -1.4,
            p_value_proxy: 0.004,
            raw_tpm: 3.2,
            reference_z: -0.6,
            direction: "down",
            significant: true,
          },
        ]}
        plot={{
          x_axis_label: "log2 FC",
          y_axis_label: "-log10 p proxy",
          x_threshold_abs: 1,
          y_threshold: 1.3,
          p_value_proxy: true,
          proxy_note: "research-only",
          total_genes_observed: 2,
          returned_points: 2,
        }}
      />,
    );

    const volcano = screen.getByRole("img", { name: "Transcriptomics DEG volcano plot" });
    const points = volcano.querySelectorAll("circle");
    expect(points).toHaveLength(2);

    fireEvent.click(points[1]);

    expect(screen.getByText(/DUP · log2FC proxy -1.40/i)).toBeInTheDocument();
    expect(Array.from(volcano.querySelectorAll('circle[r="4"]'))).toHaveLength(1);
  });

  it("keeps MA-point selection scoped to the clicked point when gene symbols repeat", () => {
    render(
      <TranscriptomicsMaPlot
        ma_plot={[
          { gene_symbol: "DUP", mean_expr_log2: 4.2, log2_fc: 1.1, significant: true },
          { gene_symbol: "DUP", mean_expr_log2: 5.1, log2_fc: -0.7, significant: false },
        ]}
      />,
    );

    const maPlot = screen.getByRole("img", { name: "Transcriptomics MA plot" });
    const points = maPlot.querySelectorAll("circle");
    expect(points).toHaveLength(2);

    fireEvent.click(points[1]);

    expect(screen.getByText(/DUP: mean log₂ = 5.10, log₂ FC = -0.70/i)).toBeInTheDocument();
    expect(Array.from(maPlot.querySelectorAll('circle[r="4"]'))).toHaveLength(1);
  });
});
