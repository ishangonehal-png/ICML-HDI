import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TranscriptomicsRawExpressionMatrix } from "./transcriptomics-raw-expression-matrix";

afterEach(() => {
  cleanup();
});

describe("TranscriptomicsRawExpressionMatrix", () => {
  it("filters by gene symbol and supports hover/select row details", () => {
    render(
      <TranscriptomicsRawExpressionMatrix
        preview={{
          available: true,
          data_source: "counts_tsv",
          unavailable_reason: null,
          total_genes_observed: 120,
          returned_rows: 3,
          preview_limit: 3,
          truncated: true,
          rows: [
            { gene_symbol: "CXCL9", raw_value: 26, normalized_log2: 4.754888, rank: 1 },
            { gene_symbol: "GZMA", raw_value: 14, normalized_log2: 3.906891, rank: 2 },
            { gene_symbol: "PRF1", raw_value: 9, normalized_log2: 3.321928, rank: 3 },
          ],
        }}
      />,
    );

    expect(screen.getByText(/Preview of raw matrix values/i)).toBeInTheDocument();

    const searchInput = screen.getByRole("searchbox", {
      name: "Search raw matrix preview by gene symbol",
    });
    fireEvent.change(searchInput, { target: { value: "CXCL" } });

    expect(screen.getByTestId("raw-matrix-row-CXCL9")).toBeInTheDocument();
    expect(screen.queryByTestId("raw-matrix-row-GZMA")).not.toBeInTheDocument();
    expect(screen.queryByTestId("raw-matrix-row-PRF1")).not.toBeInTheDocument();
    expect(screen.getByText(/CXCL9 \| raw/i)).toBeInTheDocument();

    fireEvent.change(searchInput, { target: { value: "" } });

    const prf1Row = screen.getByTestId("raw-matrix-row-PRF1");
    fireEvent.mouseEnter(prf1Row);
    expect(screen.getByText(/PRF1 \| raw/i)).toBeInTheDocument();
    fireEvent.mouseLeave(prf1Row);

    const gzmaRow = screen.getByTestId("raw-matrix-row-GZMA");
    fireEvent.click(gzmaRow);
    expect(screen.getByText(/GZMA \| raw/i)).toBeInTheDocument();
  });

  it("renders unavailable reason when preview data is missing", () => {
    render(
      <TranscriptomicsRawExpressionMatrix
        preview={{
          available: false,
          data_source: "unavailable",
          unavailable_reason: "No transcriptomics input detected for this case.",
          total_genes_observed: 0,
          returned_rows: 0,
          preview_limit: 120,
          truncated: false,
          rows: [],
        }}
      />,
    );

    expect(screen.getByText("No transcriptomics input detected for this case.")).toBeInTheDocument();
  });
});
