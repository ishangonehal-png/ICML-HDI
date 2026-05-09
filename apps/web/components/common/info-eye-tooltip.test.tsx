import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InfoEyeTooltip } from "./info-eye-tooltip";

describe("InfoEyeTooltip", () => {
  it("opens on focus/hover and exposes tooltip state through aria attributes", () => {
    const description =
      "Provisional score combines pathology and clinical signals and remains a research-only estimate.";

    render(<InfoEyeTooltip ariaLabel="Provisional score explanation" description={description} />);

    const trigger = screen.getByRole("button", {
      name: "Provisional score explanation",
    });
    const tooltip = screen.getByText(description).closest('[role="tooltip"]');

    expect(tooltip).not.toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveAttribute("aria-describedby");
    expect(tooltip).toHaveAttribute("data-open", "false");
    expect(tooltip).toHaveAttribute("aria-hidden", "true");

    fireEvent.focus(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-describedby", tooltip?.id);
    expect(tooltip).toHaveAttribute("data-open", "true");
    expect(tooltip).toHaveAttribute("aria-hidden", "false");

    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveAttribute("aria-describedby");
    expect(tooltip).toHaveAttribute("data-open", "false");

    fireEvent.mouseEnter(trigger.parentElement as HTMLElement);
    expect(tooltip).toHaveAttribute("data-open", "true");

    fireEvent.mouseLeave(trigger.parentElement as HTMLElement);
    expect(tooltip).toHaveAttribute("data-open", "false");
  });

  it("supports tap toggling and outside-pointer dismissal for mobile interactions", () => {
    render(
      <InfoEyeTooltip
        ariaLabel="Refined score explanation"
        description="Refined score extends the provisional baseline with transcriptomics evidence."
      />,
    );

    const trigger = screen.getByRole("button", {
      name: "Refined score explanation",
    });
    const tooltip = screen
      .getByText("Refined score extends the provisional baseline with transcriptomics evidence.")
      .closest('[role="tooltip"]');

    fireEvent.pointerDown(trigger, { pointerType: "touch" });
    fireEvent.click(trigger);
    expect(tooltip).toHaveAttribute("data-open", "true");

    fireEvent.pointerDown(document.body, { pointerType: "touch" });
    expect(tooltip).toHaveAttribute("data-open", "false");
  });
});
