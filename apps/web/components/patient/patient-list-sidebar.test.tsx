import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PatientListSidebar } from "./patient-list-sidebar";

vi.mock("next/link", () => ({
  default: ({
    href,
    className,
    children,
  }: {
    href: string;
    className?: string;
    children: React.ReactNode;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

describe("PatientListSidebar", () => {
  it("uses a viewport-height sidebar layout so the case list can scroll within the rail", () => {
    render(
      <PatientListSidebar
        selectedCaseId="TCGA-05-4244"
        cases={[
          {
            case_id: "TCGA-05-4244",
            stage: "IIA",
            smoking_status: "Former smoker",
            has_transcriptomics: true,
          },
        ]}
      />,
    );

    const section = screen.getByText("Patient list").closest("section");
    expect(section).not.toBeNull();
    expect(section).toHaveClass("flex", "min-h-0", "flex-col", "xl:sticky", "xl:top-6", "xl:h-[calc(100dvh-3rem)]");

    const list = screen.getByRole("list");
    expect(list).toHaveClass("min-h-0", "flex-1", "overflow-y-auto");
  });
});
