import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EnsoPathologyViewer } from "@/components/panels/enso-pathology-viewer";

const fetchMock = vi.fn();

describe("EnsoPathologyViewer", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("falls back to static preview/heatmap mode when deep-zoom is unavailable", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        deepzoom_available: false,
        deepzoom_unavailable_reason: "Slide is not indexed in Enso embeddings.",
        fallback_preview_url: "/v1/pathology/slides/TCGA-05-4244-DX1/preview/image",
        fallback_heatmap_url: "/v1/pathology/slides/TCGA-05-4244-DX1/heatmap/image",
      }),
    });

    render(
      <EnsoPathologyViewer
        slideId="TCGA-05-4244-DX1"
        fallbackPreviewUrl="/v1/pathology/slides/TCGA-05-4244-DX1/preview/image"
        fallbackHeatmapUrl="/v1/pathology/slides/TCGA-05-4244-DX1/heatmap/image"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/not indexed in enso embeddings/i)).toBeInTheDocument();
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/pathology/slides/TCGA-05-4244-DX1/viewer-config"),
      expect.objectContaining({ method: "GET" }),
    );

    expect(screen.getByAltText(/static pathology preview/i)).toBeInTheDocument();
    expect(screen.getByAltText(/static pathology heatmap/i)).toBeInTheDocument();
  });

  it("uses viewer-config DZI URL when available and falls back to static mode on 404", async () => {
    const dziUrlWithCacheBust = "/v1/pathology/slides/TCGA-05-4244-DX1/dzi?v=cache-bust-token";

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          deepzoom_available: true,
          dzi_url: dziUrlWithCacheBust,
          tile_url_template: "/v1/pathology/slides/TCGA-05-4244-DX1/tile/{level}/{tile_name}?v=cache-bust-token",
          attention_heatmap_url: "/v1/pathology/slides/TCGA-05-4244-DX1/attention-heatmap?v=cache-bust-token",
          fallback_preview_url: "/v1/pathology/slides/TCGA-05-4244-DX1/preview/image",
          fallback_heatmap_url: "/v1/pathology/slides/TCGA-05-4244-DX1/heatmap/image",
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
      });

    render(
      <EnsoPathologyViewer
        slideId="TCGA-05-4244-DX1"
        fallbackPreviewUrl="/v1/pathology/slides/TCGA-05-4244-DX1/preview/image"
        fallbackHeatmapUrl="/v1/pathology/slides/TCGA-05-4244-DX1/heatmap/image"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/dzi descriptor not found/i)).toBeInTheDocument();
    });

    expect(fetchMock).toHaveBeenCalledWith(dziUrlWithCacheBust, expect.objectContaining({ method: "GET" }));

    expect(screen.getAllByAltText(/static pathology preview/i).length).toBeGreaterThan(0);
  });

  it("does not render static image requests when viewer-config omits fallback URLs", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        deepzoom_available: false,
        deepzoom_unavailable_reason: "No local fallback assets.",
        fallback_preview_url: null,
        fallback_heatmap_url: null,
      }),
    });

    render(
      <EnsoPathologyViewer
        slideId="TCGA-05-4244-DX1"
        fallbackPreviewUrl="/v1/pathology/slides/TCGA-05-4244-DX1/preview/image"
        fallbackHeatmapUrl="/v1/pathology/slides/TCGA-05-4244-DX1/heatmap/image"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/no local fallback assets/i)).toBeInTheDocument();
    });

    expect(screen.queryByAltText(/static pathology preview/i)).not.toBeInTheDocument();
    expect(screen.queryByAltText(/static pathology heatmap/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no static preview image was found/i)).toBeInTheDocument();
  });
});
