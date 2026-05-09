import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ResearchDisclaimerBanner,
  ResearchDisclaimerFooter,
} from "./research-disclaimer";

describe("research disclaimer components", () => {
  it("renders research-only banner message", () => {
    render(<ResearchDisclaimerBanner />);

    expect(
      screen.getByText(
        "Research-only prototype — proxy estimates from public TCGA data. Not for clinical use.",
      ),
    ).toBeInTheDocument();
  });

  it("renders research-only footer message", () => {
    render(<ResearchDisclaimerFooter />);

    expect(
      screen.getByText(
        "Research-only prototype · Outputs are proxy estimates with uncertainty/provenance and no clinical validity claims.",
      ),
    ).toBeInTheDocument();
  });
});
