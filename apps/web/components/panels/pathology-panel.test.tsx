import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PathologyPanel } from "./pathology-panel";

vi.mock("@/components/panels/enso-pathology-viewer", () => ({
  EnsoPathologyViewer: ({ slideId }: { slideId: string }) => (
    <div data-testid="mock-enso-viewer">Mock viewer for {slideId}</div>
  ),
}));

const meta = {
  method: "pathology-v2",
  version: "2026.03",
  timestamp: "2026-03-08T00:00:00Z",
  proxy_estimate: true as const,
};

afterEach(() => {
  cleanup();
});

describe("PathologyPanel", () => {
  it("keeps key pathology endpoint labels paired with info-eye triggers", () => {
    render(
      <PathologyPanel
        tissue={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          fractions: [
            { tissue: "Tumor", fraction: 0.68 },
            { tissue: "Stroma", fraction: 0.22 },
          ],
          qc: {
            coverage: 0.91,
            artifact_warning: "Mild pen marks",
          },
          meta,
        }}
        heatmap={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          heatmap_uri: "/v1/pathology/slides/TCGA-05-4244-DX1/heatmap/image",
          slide_preview_uri: "/v1/pathology/slides/TCGA-05-4244-DX1/preview/image",
          viewport_hint: {
            x: 0.13,
            y: 0.21,
            width: 0.34,
            height: 0.29,
          },
          meta,
        }}
        evidence={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          top_tiles: [
            {
              tile_id: "tile-001",
              score: 0.82,
              rationale: "High-density atypical nuclei with infiltrating lymphocytes.",
              bbox: {
                x: 0.12,
                y: 0.18,
                width: 0.09,
                height: 0.08,
              },
            },
          ],
          meta,
        }}
      />,
    );

    expect(screen.getByRole("button", { name: "Pathology panel slide viewer explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel slide id explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel viewport hint values explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel viewport x explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel tissue composition fractions explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel coverage and artifact warning explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel top evidence tiles explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel tile id and score explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel selected tile state explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel tile rationale explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel tile bbox status explanation" })).toBeInTheDocument();
  });

  it("keeps fallback endpoint labels paired with info-eye explanations", () => {
    render(
      <PathologyPanel
        tissue={null}
        heatmap={null}
        evidence={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          top_tiles: [],
          meta,
        }}
      />,
    );

    expect(screen.getByText("Viewport hint unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel viewport hint unavailable explanation" })).toBeInTheDocument();
    expect(screen.getByText("Tissue composition unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel tissue composition unavailable explanation" })).toBeInTheDocument();
    expect(screen.getByText("No evidence tiles available.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pathology panel evidence tiles unavailable explanation" })).toBeInTheDocument();
  });

  it("opens tile tooltip content on keyboard focus for regression coverage", () => {
    render(
      <PathologyPanel
        tissue={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          fractions: [{ tissue: "Tumor", fraction: 0.68 }],
          qc: { coverage: 0.91 },
          meta,
        }}
        heatmap={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          heatmap_uri: "/v1/pathology/slides/TCGA-05-4244-DX1/heatmap/image",
          viewport_hint: {
            x: 0.13,
            y: 0.21,
            width: 0.34,
            height: 0.29,
          },
          meta,
        }}
        evidence={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          top_tiles: [
            {
              tile_id: "tile-001",
              score: 0.82,
              rationale: "High-density atypical nuclei.",
              bbox: null,
            },
          ],
          meta,
        }}
      />,
    );

    const tileIdScore = screen.getByRole("button", { name: "Pathology panel tile id and score explanation" });
    expect(tileIdScore).toHaveAttribute("aria-expanded", "false");

    fireEvent.focus(tileIdScore);

    expect(tileIdScore).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/stable patch identifier emitted by the pathology evidence endpoint/i)).toBeInTheDocument();
  });

  it("supports selecting evidence rows with Enter and Space keyboard interactions", () => {
    render(
      <PathologyPanel
        tissue={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          fractions: [{ tissue: "Tumor", fraction: 0.68 }],
          qc: { coverage: 0.91 },
          meta,
        }}
        heatmap={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          heatmap_uri: "/v1/pathology/slides/TCGA-05-4244-DX1/heatmap/image",
          viewport_hint: {
            x: 0.13,
            y: 0.21,
            width: 0.34,
            height: 0.29,
          },
          meta,
        }}
        evidence={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          top_tiles: [
            {
              tile_id: "tile-001",
              score: 0.82,
              rationale: "High-density atypical nuclei.",
              bbox: {
                x: 0.12,
                y: 0.18,
                width: 0.09,
                height: 0.08,
              },
            },
            {
              tile_id: "tile-002",
              score: 0.74,
              rationale: "Necrotic edge with stromal infiltration.",
              bbox: {
                x: 0.42,
                y: 0.37,
                width: 0.08,
                height: 0.07,
              },
            },
          ],
          meta,
        }}
      />,
    );

    const tileOneRow = screen.getByRole("button", { name: /tile-001/i });
    const tileTwoRow = screen.getByRole("button", { name: /tile-002/i });

    expect(tileOneRow).toHaveAttribute("aria-pressed", "true");
    expect(tileTwoRow).toHaveAttribute("aria-pressed", "false");

    fireEvent.keyDown(tileTwoRow, { key: "Enter" });

    expect(tileOneRow).toHaveAttribute("aria-pressed", "false");
    expect(tileTwoRow).toHaveAttribute("aria-pressed", "true");

    fireEvent.keyDown(tileOneRow, { key: " " });

    expect(tileOneRow).toHaveAttribute("aria-pressed", "true");
    expect(tileTwoRow).toHaveAttribute("aria-pressed", "false");
  });

  it("lets nested info-eye controls handle keyboard input without hijacking row selection", () => {
    render(
      <PathologyPanel
        tissue={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          fractions: [{ tissue: "Tumor", fraction: 0.68 }],
          qc: { coverage: 0.91 },
          meta,
        }}
        heatmap={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          heatmap_uri: "/v1/pathology/slides/TCGA-05-4244-DX1/heatmap/image",
          viewport_hint: {
            x: 0.13,
            y: 0.21,
            width: 0.34,
            height: 0.29,
          },
          meta,
        }}
        evidence={{
          case_id: "TCGA-05-4244",
          slide_id: "TCGA-05-4244-DX1",
          top_tiles: [
            {
              tile_id: "tile-001",
              score: 0.82,
              rationale: "High-density atypical nuclei.",
              bbox: {
                x: 0.12,
                y: 0.18,
                width: 0.09,
                height: 0.08,
              },
            },
            {
              tile_id: "tile-002",
              score: 0.74,
              rationale: "Necrotic edge with stromal infiltration.",
              bbox: {
                x: 0.42,
                y: 0.37,
                width: 0.08,
                height: 0.07,
              },
            },
          ],
          meta,
        }}
      />,
    );

    const tileOneRow = screen.getByRole("button", { name: /tile-001/i });
    const tileTwoRow = screen.getByRole("button", { name: /tile-002/i });

    fireEvent.click(tileTwoRow);
    expect(tileOneRow).toHaveAttribute("aria-pressed", "false");
    expect(tileTwoRow).toHaveAttribute("aria-pressed", "true");

    const tileIdScoreInfoEye = screen.getByRole("button", { name: "Pathology panel tile id and score explanation" });
    const enterEvent = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });

    tileIdScoreInfoEye.dispatchEvent(enterEvent);

    expect(enterEvent.defaultPrevented).toBe(false);
    expect(tileOneRow).toHaveAttribute("aria-pressed", "false");
    expect(tileTwoRow).toHaveAttribute("aria-pressed", "true");

    fireEvent.focus(tileIdScoreInfoEye);
    expect(tileIdScoreInfoEye).toHaveAttribute("aria-expanded", "true");
  });
});
