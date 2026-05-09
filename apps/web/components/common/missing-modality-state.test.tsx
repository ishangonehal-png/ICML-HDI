import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MissingModalityState } from "./missing-modality-state";

describe("MissingModalityState", () => {
  it("renders modality heading and default fallback description", () => {
    render(<MissingModalityState modality="Transcriptomics" />);

    expect(screen.getByText("Transcriptomics not available")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Panel remains visible for transparency. Analysis continues with available modalities only.",
      ),
    ).toBeInTheDocument();
  });

  it("renders provided custom description", () => {
    render(
      <MissingModalityState
        modality="Pathology"
        description="No compatible slide found in upload package."
      />,
    );

    expect(screen.getByText("Pathology not available")).toBeInTheDocument();
    expect(screen.getByText("No compatible slide found in upload package.")).toBeInTheDocument();
  });
});
