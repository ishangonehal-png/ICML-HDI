import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PanelShell } from "./panel-shell";

describe("PanelShell", () => {
  it("renders shared framing info-eye tooltips for title/subtitle/meta", () => {
    const copy = {
      title:
        "Fusion panel combines modality-specific endpoints into one comparative synthesis view so score movement can be traced across evidence sources.",
      subtitle:
        "This subtitle explains how provisional baseline, refined estimate, and attribution should be interpreted together during review.",
      proxyEstimate:
        "Proxy estimate indicates this card is research-only and intended for comparative interpretation rather than direct clinical decision support.",
      meta:
        "Method, version, and timestamp make the panel output auditable across reruns and pipeline changes.",
    };

    render(
      <PanelShell
        title="Fusion panel"
        subtitle="Provisional/refined score story"
        meta={{
          method: "fusion-v2",
          version: "2026.03",
          timestamp: "2026-03-08T00:00:00Z",
        }}
        tooltips={copy}
      >
        <div>Panel body</div>
      </PanelShell>,
    );

    const titleTrigger = screen.getByRole("button", {
      name: "Fusion panel title explanation",
    });
    const subtitleTrigger = screen.getByRole("button", {
      name: "Fusion panel subtitle explanation",
    });
    const proxyTrigger = screen.getByRole("button", {
      name: "Fusion panel proxy estimate explanation",
    });
    const metaTrigger = screen.getByRole("button", {
      name: "Fusion panel method/version metadata explanation",
    });

    expect(titleTrigger).toBeInTheDocument();
    expect(subtitleTrigger).toBeInTheDocument();
    expect(proxyTrigger).toBeInTheDocument();
    expect(metaTrigger).toBeInTheDocument();

    fireEvent.focus(proxyTrigger);
    const proxyTooltip = screen.getByText(copy.proxyEstimate).closest('[role="tooltip"]');
    expect(proxyTooltip).toHaveAttribute("data-open", "true");
    expect(proxyTooltip).toHaveClass("right-0");
    expect(proxyTrigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.focus(metaTrigger);
    const metaTooltip = screen.getByText(copy.meta).closest('[role="tooltip"]');
    expect(metaTooltip).toHaveAttribute("data-open", "true");
    expect(metaTooltip).toHaveClass("right-0");
    expect(metaTrigger).toHaveAttribute("aria-expanded", "true");
  });
});
