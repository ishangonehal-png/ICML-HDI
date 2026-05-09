"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import { cn } from "@/lib/utils";

interface EnsoModelOption {
  id: string;
  label: string;
}

interface NormalizedBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface EnsoPathologyViewerProps {
  slideId: string;
  className?: string;
  modelOptions?: EnsoModelOption[];
  viewportHint?: NormalizedBox | null;
  selectedEvidenceBbox?: NormalizedBox | null;
  fallbackPreviewUrl?: string | null;
  fallbackHeatmapUrl?: string | null;
}

interface ViewerConfigPayload {
  deepzoom_available?: boolean;
  deepzoom_unavailable_reason?: string | null;
  dzi_url?: string | null;
  tile_url_template?: string | null;
  attention_heatmap_url?: string | null;
  fallback_preview_url?: string | null;
  fallback_heatmap_url?: string | null;
  defaults?: {
    model_id?: string;
    level?: number;
    smooth?: boolean;
    alpha_power?: number;
  };
}

interface DziDescriptor {
  width: number;
  height: number;
  tileSize: number;
  overlap: number;
  format: string;
}

type ViewerMode = "overlay" | "slide" | "heatmap";

const DEFAULT_MODEL_OPTIONS: EnsoModelOption[] = [{ id: "lung_stage", label: "Lung stage" }];
const DEFAULT_HEATMAP_LEVEL = 2;
const DEFAULT_HEATMAP_OPACITY = 45;
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ?? "";

function parseDziDescriptor(xml: string): DziDescriptor | null {
  try {
    const parser = new DOMParser();
    const documentRoot = parser.parseFromString(xml, "application/xml");
    const imageNode = documentRoot.querySelector("Image");
    const sizeNode = documentRoot.querySelector("Size");

    if (!imageNode || !sizeNode) {
      return null;
    }

    const width = Number.parseInt(sizeNode.getAttribute("Width") ?? "", 10);
    const height = Number.parseInt(sizeNode.getAttribute("Height") ?? "", 10);
    const tileSize = Number.parseInt(imageNode.getAttribute("TileSize") ?? "", 10);
    const overlap = Number.parseInt(imageNode.getAttribute("Overlap") ?? "0", 10);
    const format = imageNode.getAttribute("Format")?.trim() || "jpeg";

    if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
      return null;
    }

    if (!Number.isFinite(tileSize) || tileSize <= 0) {
      return null;
    }

    return {
      width,
      height,
      tileSize,
      overlap: Number.isFinite(overlap) ? overlap : 0,
      format,
    };
  } catch {
    return null;
  }
}

function parsePositiveHeaderInt(value: string | null): number | null {
  if (!value) {
    return null;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }

  return parsed;
}

async function getImageDimensionsFromBlob(blob: Blob): Promise<{ width: number; height: number }> {
  if (typeof createImageBitmap === "function") {
    const bitmap = await createImageBitmap(blob);
    const dimensions = { width: bitmap.width, height: bitmap.height };
    bitmap.close();
    return dimensions;
  }

  return await new Promise((resolve, reject) => {
    const image = new Image();
    const objectUrl = URL.createObjectURL(blob);

    image.onload = () => {
      resolve({ width: image.naturalWidth, height: image.naturalHeight });
      URL.revokeObjectURL(objectUrl);
    };

    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("Unable to decode heatmap image blob."));
    };

    image.src = objectUrl;
  });
}

function clampBox(box: NormalizedBox): NormalizedBox {
  const x = Math.min(Math.max(box.x, 0), 1);
  const y = Math.min(Math.max(box.y, 0), 1);
  const width = Math.min(Math.max(box.width, 0), 1 - x);
  const height = Math.min(Math.max(box.height, 0), 1 - y);

  return { x, y, width, height };
}

function normalizedBoxStyle(box: NormalizedBox | null | undefined): CSSProperties | undefined {
  if (!box) {
    return undefined;
  }

  const normalized = clampBox(box);
  return {
    left: `${(normalized.x * 100).toFixed(4)}%`,
    top: `${(normalized.y * 100).toFixed(4)}%`,
    width: `${(normalized.width * 100).toFixed(4)}%`,
    height: `${(normalized.height * 100).toFixed(4)}%`,
  };
}

function resolveApiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  if (!API_BASE_URL) {
    return path;
  }

  const base = API_BASE_URL.replace(/\/$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalizedPath}`;
}

function buildViewerConfigUrl(slideId: string): string {
  return resolveApiUrl(`/v1/pathology/slides/${encodeURIComponent(slideId)}/viewer-config`);
}

function buildDziUrl(slideId: string): string {
  return resolveApiUrl(`/v1/pathology/slides/${encodeURIComponent(slideId)}/dzi`);
}

function buildTileUrlTemplate(slideId: string): string {
  return resolveApiUrl(`/v1/pathology/slides/${encodeURIComponent(slideId)}/tile/{level}/{tile_name}`);
}

function buildTileUrl(slideId: string, level: number, tileSpec: string): string {
  return resolveApiUrl(`/v1/pathology/slides/${encodeURIComponent(slideId)}/tile/${level}/${tileSpec}`);
}

function buildAttentionHeatmapBaseUrl(slideId: string): string {
  return resolveApiUrl(`/v1/pathology/slides/${encodeURIComponent(slideId)}/attention-heatmap`);
}

function buildHeatmapUrl(baseUrl: string, modelId: string, level: number, smooth: boolean, alphaPower: number): string {
  const queryStartIndex = baseUrl.indexOf("?");
  const endpoint = queryStartIndex >= 0 ? baseUrl.slice(0, queryStartIndex) : baseUrl;
  const existingQuery = queryStartIndex >= 0 ? baseUrl.slice(queryStartIndex + 1) : "";

  const query = new URLSearchParams({
    ...Object.fromEntries(new URLSearchParams(existingQuery)),
    model_id: modelId,
    level: String(level),
    smooth: smooth ? "true" : "false",
    alpha_power: alphaPower.toFixed(2),
  });

  return `${endpoint}?${query.toString()}`;
}

function parseNonNegativeInt(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }

  const rounded = Math.floor(value);
  if (rounded < 0) {
    return null;
  }

  return rounded;
}

function parsePositiveNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }

  return value;
}

function resolveConfiguredUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) {
    return null;
  }
  return resolveApiUrl(value);
}

function resolveTileUrl(tileUrlTemplate: string | null, slideId: string, level: number, tileSpec: string): string {
  if (tileUrlTemplate && tileUrlTemplate.includes("{level}") && tileUrlTemplate.includes("{tile_name}")) {
    return tileUrlTemplate.replace("{level}", String(level)).replace("{tile_name}", tileSpec);
  }
  return buildTileUrl(slideId, level, tileSpec);
}

function applyHeatmapInterpolation(tiledImage: any, smooth: boolean): void {
  try {
    const drawer = tiledImage?._drawer;
    const canvas = drawer?.canvas;

    if (canvas) {
      canvas.style.imageRendering = smooth ? "auto" : "pixelated";
      const context = canvas.getContext("2d");
      if (context) {
        context.imageSmoothingEnabled = smooth;
      }
    }

    if (drawer?.setImageSmoothingEnabled) {
      drawer.setImageSmoothingEnabled(smooth);
    }
  } catch {
    // Best-effort visual tuning; safe to ignore unsupported internals.
  }
}

function getErrorMessage(status: number, body: string): string {
  const fallback = `Heatmap overlay unavailable (HTTP ${status}).`;
  if (!body) {
    return fallback;
  }

  try {
    const payload = JSON.parse(body) as
      | { detail?: string | { message?: string; error?: string }; message?: string; error?: string }
      | undefined;

    if (!payload) {
      return fallback;
    }

    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }

    if (payload.detail && typeof payload.detail === "object") {
      if (typeof payload.detail.message === "string" && payload.detail.message.trim()) {
        return payload.detail.message;
      }
      if (typeof payload.detail.error === "string" && payload.detail.error.trim()) {
        return payload.detail.error;
      }
    }

    if (typeof payload.message === "string" && payload.message.trim()) {
      return payload.message;
    }

    if (typeof payload.error === "string" && payload.error.trim()) {
      return payload.error;
    }
  } catch {
    // Ignore parse errors and use fallback.
  }

  return fallback;
}

function stringifyConsoleArg(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function isBenignTileAbortConsoleError(args: unknown[]): boolean {
  const text = args.map(stringifyConsoleArg).join(" ");
  return /tile\s+.*failed to load/i.test(text) && /image load aborted/i.test(text);
}

function installOpenSeadragonConsoleFilter(OpenSeadragon: any): (() => void) | null {
  const osdConsole = OpenSeadragon?.console;
  if (!osdConsole || typeof osdConsole !== "object") {
    return null;
  }

  const originalError =
    typeof osdConsole.error === "function" ? osdConsole.error.bind(osdConsole) : console.error.bind(console);

  const filteredConsole = {
    ...osdConsole,
    error: (...args: unknown[]) => {
      if (isBenignTileAbortConsoleError(args)) {
        return;
      }
      originalError(...args);
    },
  };

  OpenSeadragon.console = filteredConsole;

  return () => {
    OpenSeadragon.console = osdConsole;
  };
}

export function EnsoPathologyViewer({
  slideId,
  className,
  modelOptions,
  viewportHint,
  selectedEvidenceBbox,
  fallbackPreviewUrl,
  fallbackHeatmapUrl,
}: EnsoPathologyViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewportOverlayRef = useRef<HTMLDivElement | null>(null);
  const evidenceOverlayRef = useRef<HTMLDivElement | null>(null);

  const viewerRef = useRef<any>(null);
  const openSeadragonRef = useRef<any>(null);
  const restoreOpenSeadragonConsoleRef = useRef<(() => void) | null>(null);
  const baseLayerRef = useRef<any>(null);
  const heatmapLayerRef = useRef<any>(null);
  const heatmapObjectUrlRef = useRef<string | null>(null);

  const [viewerReady, setViewerReady] = useState(false);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [heatmapError, setHeatmapError] = useState<string | null>(null);
  const [heatmapLoaded, setHeatmapLoaded] = useState(false);
  const [deepzoomAvailable, setDeepzoomAvailable] = useState<boolean | null>(null);
  const [deepzoomUnavailableReason, setDeepzoomUnavailableReason] = useState<string | null>(null);
  const [resolvedDziUrl, setResolvedDziUrl] = useState<string | null>(null);
  const [resolvedTileUrlTemplate, setResolvedTileUrlTemplate] = useState<string | null>(null);
  const [resolvedAttentionHeatmapUrl, setResolvedAttentionHeatmapUrl] = useState<string | null>(null);
  const [resolvedFallbackPreviewUrl, setResolvedFallbackPreviewUrl] = useState<string | null>(null);
  const [resolvedFallbackHeatmapUrl, setResolvedFallbackHeatmapUrl] = useState<string | null>(null);

  const [viewerMode, setViewerMode] = useState<ViewerMode>("overlay");
  const [heatmapLevel, setHeatmapLevel] = useState(DEFAULT_HEATMAP_LEVEL);
  const [heatmapOpacity, setHeatmapOpacity] = useState(DEFAULT_HEATMAP_OPACITY);
  const [smoothInterpolation, setSmoothInterpolation] = useState(true);
  const [alphaPower, setAlphaPower] = useState(0.7);
  const [showViewportOverlay, setShowViewportOverlay] = useState(true);
  const [showEvidenceOverlay, setShowEvidenceOverlay] = useState(true);

  const resolvedModelOptions = useMemo(
    () => (modelOptions && modelOptions.length > 0 ? modelOptions : DEFAULT_MODEL_OPTIONS),
    [modelOptions],
  );
  const [modelId, setModelId] = useState(resolvedModelOptions[0]?.id ?? "lung_stage");

  useEffect(() => {
    const nextModelId = resolvedModelOptions[0]?.id;
    if (!nextModelId) {
      return;
    }

    if (!resolvedModelOptions.some((entry) => entry.id === modelId)) {
      setModelId(nextModelId);
    }
  }, [modelId, resolvedModelOptions]);

  useEffect(() => {
    const defaultModelId = resolvedModelOptions[0]?.id ?? "lung_stage";
    setModelId(defaultModelId);
    setViewerMode("overlay");
    setHeatmapOpacity(DEFAULT_HEATMAP_OPACITY);
    setShowViewportOverlay(true);
    setShowEvidenceOverlay(true);
  }, [slideId, resolvedModelOptions]);

  useEffect(() => {
    let cancelled = false;

    setDeepzoomAvailable(null);
    setDeepzoomUnavailableReason(null);
    setViewerReady(false);
    setViewerError(null);
    setHeatmapError(null);
    setHeatmapLoaded(false);
    setResolvedDziUrl(null);
    setResolvedTileUrlTemplate(null);
    setResolvedAttentionHeatmapUrl(null);
    setResolvedFallbackPreviewUrl(null);
    setResolvedFallbackHeatmapUrl(null);
    setHeatmapLevel(DEFAULT_HEATMAP_LEVEL);
    setSmoothInterpolation(true);
    setAlphaPower(0.7);

    const loadViewerAvailability = async () => {
      try {
        const response = await fetch(buildViewerConfigUrl(slideId), { method: "GET" });
        if (!response.ok) {
          throw new Error(`viewer-config ${response.status}`);
        }

        const payload = (await response.json()) as ViewerConfigPayload;
        if (cancelled) {
          return;
        }

        const available =
          typeof payload.deepzoom_available === "boolean" ? payload.deepzoom_available : true;

        setDeepzoomAvailable(available);
        setDeepzoomUnavailableReason(
          typeof payload.deepzoom_unavailable_reason === "string" && payload.deepzoom_unavailable_reason.trim()
            ? payload.deepzoom_unavailable_reason
            : null,
        );
        setResolvedDziUrl(resolveConfiguredUrl(payload.dzi_url) ?? buildDziUrl(slideId));
        setResolvedTileUrlTemplate(resolveConfiguredUrl(payload.tile_url_template) ?? buildTileUrlTemplate(slideId));
        setResolvedAttentionHeatmapUrl(
          resolveConfiguredUrl(payload.attention_heatmap_url) ?? buildAttentionHeatmapBaseUrl(slideId),
        );

        const nextFallbackPreviewUrl = resolveConfiguredUrl(payload.fallback_preview_url);
        const nextFallbackHeatmapUrl = resolveConfiguredUrl(payload.fallback_heatmap_url);

        setResolvedFallbackPreviewUrl(nextFallbackPreviewUrl);
        setResolvedFallbackHeatmapUrl(nextFallbackHeatmapUrl);

        const defaultHeatmapLevel = parseNonNegativeInt(payload.defaults?.level);
        if (defaultHeatmapLevel !== null) {
          setHeatmapLevel(defaultHeatmapLevel);
        }

        if (typeof payload.defaults?.smooth === "boolean") {
          setSmoothInterpolation(payload.defaults.smooth);
        }

        const defaultAlphaPower = parsePositiveNumber(payload.defaults?.alpha_power);
        if (defaultAlphaPower !== null) {
          setAlphaPower(defaultAlphaPower);
        }

        const configuredModelId =
          typeof payload.defaults?.model_id === "string" ? payload.defaults.model_id.trim() : "";
        if (configuredModelId && resolvedModelOptions.some((entry) => entry.id === configuredModelId)) {
          setModelId(configuredModelId);
        }
      } catch {
        if (cancelled) {
          return;
        }

        // Preserve legacy behavior when viewer-config is unavailable.
        setDeepzoomAvailable(true);
        setDeepzoomUnavailableReason(null);
        setResolvedDziUrl(buildDziUrl(slideId));
        setResolvedTileUrlTemplate(buildTileUrlTemplate(slideId));
        setResolvedAttentionHeatmapUrl(buildAttentionHeatmapBaseUrl(slideId));
        setResolvedFallbackPreviewUrl(fallbackPreviewUrl ? resolveApiUrl(fallbackPreviewUrl) : null);
        setResolvedFallbackHeatmapUrl(fallbackHeatmapUrl ? resolveApiUrl(fallbackHeatmapUrl) : null);
      }
    };

    loadViewerAvailability();

    return () => {
      cancelled = true;
    };
  }, [slideId, fallbackPreviewUrl, fallbackHeatmapUrl, resolvedModelOptions]);

  useEffect(() => {
    let cancelled = false;

    const initializeViewer = async () => {
      if (deepzoomAvailable !== true) {
        return;
      }

      if (!containerRef.current) {
        return;
      }

      setViewerReady(false);
      setViewerError(null);
      setHeatmapError(null);
      setHeatmapLoaded(false);

      const descriptorResponse = await fetch(resolvedDziUrl ?? buildDziUrl(slideId), { method: "GET" });
      if (!descriptorResponse.ok) {
        if (descriptorResponse.status === 404) {
          if (!cancelled) {
            setDeepzoomAvailable(false);
            setDeepzoomUnavailableReason("DZI descriptor not found for this slide (404). Showing static fallback.");
          }
          return;
        }

        throw new Error(`Failed to load DZI descriptor (${descriptorResponse.status}).`);
      }

      const descriptorXml = await descriptorResponse.text();
      const descriptor = parseDziDescriptor(descriptorXml);
      if (!descriptor) {
        throw new Error("DZI descriptor is malformed.");
      }

      if (cancelled || !containerRef.current) {
        return;
      }

      const module = await import("openseadragon");
      const OpenSeadragon = module.default ?? module;
      openSeadragonRef.current = OpenSeadragon;

      if (restoreOpenSeadragonConsoleRef.current) {
        restoreOpenSeadragonConsoleRef.current();
        restoreOpenSeadragonConsoleRef.current = null;
      }
      restoreOpenSeadragonConsoleRef.current = installOpenSeadragonConsoleFilter(OpenSeadragon);

      const tileSource = {
        width: descriptor.width,
        height: descriptor.height,
        tileSize: descriptor.tileSize,
        tileOverlap: descriptor.overlap,
        minLevel: 0,
        crossOriginPolicy: "Anonymous",
        getTileUrl(level: number, x: number, y: number) {
          return resolveTileUrl(resolvedTileUrlTemplate, slideId, level, `${x}_${y}.${descriptor.format}`);
        },
      };

      const viewer = OpenSeadragon({
        element: containerRef.current,
        tileSources: tileSource,
        prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/images/",
        showNavigator: true,
        navigatorPosition: "BOTTOM_RIGHT",
        navigatorAutoFade: false,
        showZoomControl: false,
        showHomeControl: false,
        showFullPageControl: false,
        showRotationControl: false,
        visibilityRatio: 1,
        constrainDuringPan: true,
        crossOriginPolicy: "Anonymous",
        gestureSettingsMouse: {
          clickToZoom: false,
          dblClickToZoom: true,
          scrollToZoom: true,
        },
      });

      viewer.addHandler("open", () => {
        baseLayerRef.current = viewer.world.getItemAt(0) ?? null;
        setViewerReady(true);
      });

      viewer.addHandler("open-failed", () => {
        setViewerError("Unable to load WSI tiles for this slide.");
        setViewerReady(false);
      });

      viewer.addHandler("tile-load-failed", (event: { message?: string }) => {
        const message = event?.message ?? "";
        if (isBenignTileAbortConsoleError([message]) || cancelled) {
          return;
        }

        // OpenSeadragon can emit transient tile-load failures (e.g., cancellation
        // during rapid zoom/pan or out-of-range probes) while the viewer remains
        // healthy. Avoid surfacing a persistent fatal banner for those events.
        // Fatal startup failures are handled by `open-failed` above.
      });

      viewerRef.current = viewer;
    };

    initializeViewer().catch((error: unknown) => {
      if (cancelled) {
        return;
      }

      const message = error instanceof Error ? error.message : "Failed to initialize viewer.";
      setViewerError(message);
      setViewerReady(false);
    });

    return () => {
      cancelled = true;
      setViewerReady(false);
      baseLayerRef.current = null;
      heatmapLayerRef.current = null;

      if (heatmapObjectUrlRef.current) {
        URL.revokeObjectURL(heatmapObjectUrlRef.current);
        heatmapObjectUrlRef.current = null;
      }

      if (viewerRef.current) {
        try {
          viewerRef.current.destroy();
        } catch {
          // Ignore cleanup failures.
        }
        viewerRef.current = null;
      }

      if (restoreOpenSeadragonConsoleRef.current) {
        restoreOpenSeadragonConsoleRef.current();
        restoreOpenSeadragonConsoleRef.current = null;
      }
    };
  }, [slideId, deepzoomAvailable, resolvedDziUrl, resolvedTileUrlTemplate]);

  useEffect(() => {
    if (deepzoomAvailable !== true || !viewerReady || !viewerRef.current || !baseLayerRef.current) {
      return;
    }

    const viewer = viewerRef.current;
    const baseLayer = baseLayerRef.current;

    if (heatmapLayerRef.current) {
      try {
        viewer.world.removeItem(heatmapLayerRef.current);
      } catch {
        // Ignore stale layer cleanup issues.
      }
      heatmapLayerRef.current = null;
    }

    if (heatmapObjectUrlRef.current) {
      URL.revokeObjectURL(heatmapObjectUrlRef.current);
      heatmapObjectUrlRef.current = null;
    }

    setHeatmapLoaded(false);
    setHeatmapError(null);

    let cancelled = false;

    const loadHeatmapOverlay = async () => {
      const requestUrl = buildHeatmapUrl(
        resolvedAttentionHeatmapUrl ?? buildAttentionHeatmapBaseUrl(slideId),
        modelId,
        heatmapLevel,
        smoothInterpolation,
        alphaPower,
      );
      const response = await fetch(requestUrl, { method: "GET" });
      if (!response.ok) {
        const responseBody = await response.text().catch(() => "");
        throw new Error(getErrorMessage(response.status, responseBody));
      }

      const heatmapBlob = await response.blob();
      const dimensions = await getImageDimensionsFromBlob(heatmapBlob);

      if (dimensions.width <= 0 || dimensions.height <= 0) {
        throw new Error("Heatmap image has invalid dimensions.");
      }

      const contentSize = baseLayer.getContentSize();
      const bounds = baseLayer.getBounds();

      const fallbackCoverageWidth = Math.ceil(contentSize.x / 224) * 224;
      const fallbackCoverageHeight = Math.ceil(contentSize.y / 224) * 224;
      const coverageWidth =
        parsePositiveHeaderInt(response.headers.get("X-Coverage-Width")) ?? fallbackCoverageWidth;
      const coverageHeight =
        parsePositiveHeaderInt(response.headers.get("X-Coverage-Height")) ?? fallbackCoverageHeight;

      const widthScale = bounds.width / contentSize.x;
      const heightScale = bounds.height / contentSize.y;

      const overlayWorldWidth = coverageWidth * widthScale;
      const overlayWorldHeight = coverageHeight * heightScale;
      const imageAspectRatio = dimensions.width / dimensions.height;
      const targetAspectRatio = overlayWorldWidth / overlayWorldHeight;

      const heatmapObjectUrl = URL.createObjectURL(heatmapBlob);
      heatmapObjectUrlRef.current = heatmapObjectUrl;

      viewer.addSimpleImage({
        url: heatmapObjectUrl,
        x: bounds.x,
        y: bounds.y,
        // OpenSeadragon warns when both width and height are set for a TiledImage.
        // Set width only and let OSD derive height from the source image ratio.
        width: overlayWorldWidth,
        crossOriginPolicy: "Anonymous",
        opacity: 0,
        success: (event: { item?: any }) => {
          const tileImage = event.item;
          if (!tileImage) {
            return;
          }

          if (cancelled) {
            try {
              viewer.world.removeItem(tileImage);
            } catch {
              // Ignore cleanup failures.
            }
            return;
          }

          // If image ratio and expected coverage ratio diverge slightly, align to backend coverage.
          if (Number.isFinite(imageAspectRatio) && Number.isFinite(targetAspectRatio)) {
            const aspectDelta = Math.abs(imageAspectRatio - targetAspectRatio);
            if (aspectDelta > 1e-3) {
              try {
                tileImage.setHeight(overlayWorldHeight, true);
              } catch {
                // Keep best-effort overlay alignment if setHeight is unavailable.
              }
            }
          }

          heatmapLayerRef.current = tileImage;
          applyHeatmapInterpolation(tileImage, smoothInterpolation);
          setHeatmapLoaded(true);
          setHeatmapError(null);
        },
        error: () => {
          if (cancelled) {
            return;
          }

          setHeatmapLoaded(false);
          setHeatmapError("Heatmap overlay unavailable for the selected settings.");
        },
      });
    };

    loadHeatmapOverlay().catch((error: unknown) => {
      if (cancelled) {
        return;
      }

      const message = error instanceof Error ? error.message : "Heatmap overlay unavailable.";
      setHeatmapLoaded(false);
      setHeatmapError(message);
    });

    return () => {
      cancelled = true;
    };
  }, [deepzoomAvailable, viewerReady, slideId, modelId, heatmapLevel, smoothInterpolation, alphaPower, resolvedAttentionHeatmapUrl]);

  useEffect(() => {
    const baseLayer = baseLayerRef.current;
    const heatmapLayer = heatmapLayerRef.current;

    if (!baseLayer) {
      return;
    }

    const showHeatmapLayer = viewerMode !== "slide";
    if (heatmapLayer) {
      const overlayOpacity = viewerMode === "overlay" ? heatmapOpacity / 100 : 1;
      heatmapLayer.setOpacity(showHeatmapLayer ? overlayOpacity : 0);
      applyHeatmapInterpolation(heatmapLayer, smoothInterpolation);
    }

    const canHideBaseLayer = viewerMode === "heatmap" && showHeatmapLayer && heatmapLoaded && !heatmapError;
    baseLayer.setOpacity(canHideBaseLayer ? 0 : 1);
  }, [viewerMode, heatmapOpacity, heatmapLoaded, heatmapError, smoothInterpolation]);

  useEffect(() => {
    const viewer = viewerRef.current;
    const baseLayer = baseLayerRef.current;
    const OpenSeadragon = openSeadragonRef.current;

    const viewportElement = viewportOverlayRef.current;
    const evidenceElement = evidenceOverlayRef.current;

    if (!viewer || !baseLayer || !OpenSeadragon || !viewerReady) {
      return;
    }

    const setOverlay = (element: HTMLDivElement | null, box: NormalizedBox | null | undefined) => {
      if (!element) {
        return;
      }

      if (!box) {
        element.style.display = "none";
        return;
      }

      const contentSize = baseLayer.getContentSize();
      const normalized = clampBox(box);

      const x = normalized.x * contentSize.x;
      const y = normalized.y * contentSize.y;
      const width = normalized.width * contentSize.x;
      const height = normalized.height * contentSize.y;

      const topLeftViewport = baseLayer.imageToViewportCoordinates(new OpenSeadragon.Point(x, y));
      const bottomRightViewport = baseLayer.imageToViewportCoordinates(
        new OpenSeadragon.Point(x + width, y + height),
      );

      const topLeftPx = viewer.viewport.pixelFromPoint(topLeftViewport, true);
      const bottomRightPx = viewer.viewport.pixelFromPoint(bottomRightViewport, true);

      const left = Math.min(topLeftPx.x, bottomRightPx.x);
      const top = Math.min(topLeftPx.y, bottomRightPx.y);
      const pixelWidth = Math.max(Math.abs(bottomRightPx.x - topLeftPx.x), 1);
      const pixelHeight = Math.max(Math.abs(bottomRightPx.y - topLeftPx.y), 1);

      element.style.display = "block";
      element.style.left = `${left}px`;
      element.style.top = `${top}px`;
      element.style.width = `${pixelWidth}px`;
      element.style.height = `${pixelHeight}px`;
    };

    const syncOverlays = () => {
      setOverlay(viewportElement, showViewportOverlay ? viewportHint : null);
      setOverlay(evidenceElement, showEvidenceOverlay ? selectedEvidenceBbox : null);
    };

    syncOverlays();
    viewer.addHandler("open", syncOverlays);
    viewer.addHandler("animation", syncOverlays);
    viewer.addHandler("resize", syncOverlays);

    return () => {
      viewer.removeHandler("open", syncOverlays);
      viewer.removeHandler("animation", syncOverlays);
      viewer.removeHandler("resize", syncOverlays);

      if (viewportElement) {
        viewportElement.style.display = "none";
      }
      if (evidenceElement) {
        evidenceElement.style.display = "none";
      }
    };
  }, [viewerReady, viewportHint, selectedEvidenceBbox, showViewportOverlay, showEvidenceOverlay]);

  useEffect(() => {
    if (deepzoomAvailable === false && !resolvedFallbackHeatmapUrl && viewerMode !== "slide") {
      setViewerMode("slide");
    }
  }, [deepzoomAvailable, resolvedFallbackHeatmapUrl, viewerMode]);

  const usingStaticFallback = deepzoomAvailable === false;
  const fallbackBaseImageUrl = resolvedFallbackPreviewUrl ?? resolvedFallbackHeatmapUrl;
  const fallbackHeatmapImageUrl = resolvedFallbackHeatmapUrl;
  const staticFallbackUsesHeatmapBase =
    resolvedFallbackPreviewUrl === null && resolvedFallbackHeatmapUrl !== null;
  const shouldRenderStaticHeatmapOverlay =
    Boolean(fallbackHeatmapImageUrl) && viewerMode !== "slide" && !staticFallbackUsesHeatmapBase;

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
        <label className="flex items-center gap-1">
          <span className="uppercase tracking-wide text-[11px]">Model</span>
          <InfoEyeTooltip
            ariaLabel="Pathology viewer model selector explanation"
            content="Model selects which pathology endpoint generates the attention map, such as stage-related versus alternate trained signatures. Different models can highlight different morphology on the same slide. Use this switch to compare hypotheses, then verify whether evidence tiles and downstream fusion behavior remain consistent before trusting a single visual narrative."
          />
          <select
            value={modelId}
            onChange={(event) => setModelId(event.target.value)}
            disabled={usingStaticFallback}
            className="rounded border border-shell-border bg-slate-900/70 px-2 py-1 text-xs text-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
            aria-label="Heatmap model"
          >
            {resolvedModelOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <div className="mx-1 flex items-center gap-1 text-slate-500">
          <span className="text-[11px] uppercase tracking-wide">Mode</span>
          <InfoEyeTooltip
            ariaLabel="Pathology viewer mode controls explanation"
            content="Mode controls how you combine slide pixels with model attention. Original shows raw histology only, Overlay blends attention on top of tissue, and Heatmap hides tissue to emphasize relative activation intensity. Toggling modes helps separate morphology from saliency and can reveal whether a hotspot is plausible or mainly a visualization artifact."
          />
        </div>
        <button
          type="button"
          onClick={() => setViewerMode("slide")}
          className={`rounded border px-2 py-1 transition ${
            viewerMode === "slide"
              ? "border-cyan-300 bg-cyan-900/30 text-cyan-100"
              : "border-shell-border bg-slate-900/40 text-slate-300 hover:border-cyan-300/60"
          }`}
          aria-label="Viewer mode original slide"
        >
          Original
        </button>
        <button
          type="button"
          onClick={() => setViewerMode("overlay")}
          disabled={usingStaticFallback && !fallbackHeatmapImageUrl}
          className={`rounded border px-2 py-1 transition disabled:cursor-not-allowed disabled:opacity-60 ${
            viewerMode === "overlay"
              ? "border-cyan-300 bg-cyan-900/30 text-cyan-100"
              : "border-shell-border bg-slate-900/40 text-slate-300 hover:border-cyan-300/60"
          }`}
          aria-label="Viewer mode overlay"
        >
          Overlay
        </button>
        <button
          type="button"
          onClick={() => setViewerMode("heatmap")}
          disabled={usingStaticFallback && !fallbackHeatmapImageUrl}
          className={`rounded border px-2 py-1 transition disabled:cursor-not-allowed disabled:opacity-60 ${
            viewerMode === "heatmap"
              ? "border-cyan-300 bg-cyan-900/30 text-cyan-100"
              : "border-shell-border bg-slate-900/40 text-slate-300 hover:border-cyan-300/60"
          }`}
          aria-label="Viewer mode heatmap"
        >
          Heatmap
        </button>

        <label className="ml-auto flex items-center gap-1">
          <span className="uppercase tracking-wide text-[11px]">Smooth</span>
          <InfoEyeTooltip
            ariaLabel="Pathology viewer smooth interpolation explanation"
            content="Smooth interpolation blends neighboring heatmap values to reduce blocky tile edges during zoom. Turning it off shows sharper, pixelated boundaries that expose raw tiling structure. Keep smooth on for presentation and quick reading, but disable it when debugging spatial precision, tile seams, or whether a hotspot is driven by interpolation rather than model output."
          />
          <input
            type="checkbox"
            checked={smoothInterpolation}
            onChange={(event) => setSmoothInterpolation(event.target.checked)}
            disabled={usingStaticFallback}
            className="h-4 w-4 accent-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
            aria-label="Smooth interpolation"
          />
        </label>
      </div>

      <div className="grid gap-2 text-xs text-slate-300 sm:grid-cols-2">
        <label className="flex items-center gap-2">
          <span className="w-24 uppercase tracking-wide text-[11px]">Opacity</span>
          <InfoEyeTooltip
            ariaLabel="Pathology viewer heatmap opacity explanation"
            content="Opacity adjusts how strongly the attention layer overlays the base slide when Overlay mode is active. Lower values preserve histology detail, while higher values emphasize saliency patterns. Tune this dynamically while zooming so cellular context stays visible where needed, especially when reviewing ambiguous boundaries between tumor-rich and non-tumor regions."
          />
          <input
            type="range"
            min={10}
            max={100}
            step={5}
            value={heatmapOpacity}
            onChange={(event) => setHeatmapOpacity(Number(event.target.value))}
            className="h-1 flex-1 accent-cyan-400"
            aria-label="Heatmap opacity"
          />
          <span className="w-10 text-right text-[11px]">{heatmapOpacity}%</span>
        </label>

        <label className="flex items-center gap-2">
          <span className="w-24 uppercase tracking-wide text-[11px]">Sensitivity</span>
          <InfoEyeTooltip
            ariaLabel="Pathology viewer heatmap sensitivity explanation"
            content="Sensitivity (alpha power) controls how aggressively attention values map to color intensity. Higher sensitivity boosts weaker signals and can surface subtle regions, while lower sensitivity suppresses noise and emphasizes dominant hotspots. Large changes can alter visual interpretation without changing predictions, so compare multiple settings before drawing conclusions from marginal areas."
          />
          <input
            type="range"
            min={0.1}
            max={1.5}
            step={0.05}
            value={alphaPower}
            onChange={(event) => setAlphaPower(Number(event.target.value))}
            disabled={usingStaticFallback}
            className="h-1 flex-1 accent-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
            aria-label="Heatmap sensitivity"
          />
          <span className="w-10 text-right text-[11px]">{alphaPower.toFixed(2)}</span>
        </label>
      </div>

      <div className="relative aspect-[16/10] overflow-hidden rounded-md border border-shell-border bg-slate-950/80">
        {usingStaticFallback ? (
          <>
            {fallbackBaseImageUrl ? (
              <img
                src={fallbackBaseImageUrl}
                alt={`Static pathology preview for ${slideId}`}
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center px-4 text-center text-sm text-slate-300">
                Deep-zoom unavailable and no static preview image was found.
              </div>
            )}

            {shouldRenderStaticHeatmapOverlay ? (
              <img
                src={fallbackHeatmapImageUrl ?? undefined}
                alt={`Static pathology heatmap for ${slideId}`}
                className="pointer-events-none absolute inset-0 h-full w-full object-cover"
                style={{ opacity: viewerMode === "overlay" ? heatmapOpacity / 100 : 1 }}
              />
            ) : null}

            {showViewportOverlay && viewportHint ? (
              <div
                aria-label="Viewport hint"
                className="pointer-events-none absolute border border-cyan-300 bg-cyan-300/10"
                style={normalizedBoxStyle(viewportHint)}
              />
            ) : null}
            {showEvidenceOverlay && selectedEvidenceBbox ? (
              <div
                aria-label="Selected evidence tile"
                className="pointer-events-none absolute border-2 border-amber-300 bg-amber-300/20"
                style={normalizedBoxStyle(selectedEvidenceBbox)}
              />
            ) : null}
          </>
        ) : (
          <>
            <div ref={containerRef} className="h-full w-full" />

            <div
              ref={viewportOverlayRef}
              aria-label="Viewport hint"
              className="pointer-events-none absolute hidden border border-cyan-300 bg-cyan-300/10"
            />
            <div
              ref={evidenceOverlayRef}
              aria-label="Selected evidence tile"
              className="pointer-events-none absolute hidden border-2 border-amber-300 bg-amber-300/20"
            />
          </>
        )}

        <div className="pointer-events-auto absolute bottom-2 left-2 flex items-center gap-2 rounded border border-black/50 bg-black/60 px-2 py-1 text-[11px] text-slate-100">
          <button
            type="button"
            onClick={() => setShowViewportOverlay((current) => !current)}
            className={`rounded border px-1.5 py-0.5 ${
              showViewportOverlay ? "border-cyan-300 text-cyan-100" : "border-slate-500 text-slate-300"
            }`}
            aria-label="Toggle viewport overlay"
          >
            Viewport
          </button>
          <button
            type="button"
            onClick={() => setShowEvidenceOverlay((current) => !current)}
            className={`rounded border px-1.5 py-0.5 ${
              showEvidenceOverlay ? "border-amber-300 text-amber-100" : "border-slate-500 text-slate-300"
            }`}
            aria-label="Toggle evidence overlay"
          >
            Evidence box
          </button>
          <InfoEyeTooltip
            ariaLabel="Pathology viewer overlay toggles explanation"
            content="Viewport toggles the endpoint-provided viewport_hint box, while Evidence box toggles the selected tile bbox from the evidence endpoint. Both overlays use normalized coordinates projected onto the current view. If no bbox was returned for a tile, the evidence toggle has nothing to draw. Use these controls to isolate global focus versus tile-specific support."
          />
        </div>

        {deepzoomAvailable === null && !viewerError ? (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-950/70 text-sm text-slate-300">
            Checking deep-zoom availability…
          </div>
        ) : null}

        {deepzoomAvailable === true && !viewerReady && !viewerError ? (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-950/70 text-sm text-slate-300">
            Loading whole-slide viewer…
          </div>
        ) : null}

        {!usingStaticFallback && viewerError ? (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-950/80 px-4 text-center text-sm text-rose-200">
            {viewerError}
          </div>
        ) : null}

        {!usingStaticFallback && heatmapError ? (
          <div className="absolute bottom-10 left-2 right-2 rounded border border-rose-400/40 bg-rose-900/40 px-2 py-1 text-xs text-rose-100">
            {heatmapError}
          </div>
        ) : null}

        {usingStaticFallback ? (
          <div className="absolute right-2 top-2 max-w-[85%] rounded border border-amber-300/50 bg-amber-900/40 px-2 py-1 text-[11px] text-amber-100">
            <div className="flex items-start gap-1">
              <span>{deepzoomUnavailableReason ?? "Deep-zoom unavailable. Showing static preview/heatmap fallback."}</span>
              <InfoEyeTooltip
                ariaLabel="Pathology viewer deep-zoom fallback warning explanation"
                content="This warning means the viewer-config endpoint reported deepzoom_available=false, so tiles cannot be streamed for pan/zoom. The panel falls back to static preview and optional static heatmap images when URLs are available. Overlay boxes still use normalized endpoint coordinates, but spatial precision and zoom-level inspection are limited compared with live deep-zoom mode."
              />
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex items-center gap-2 text-[11px] text-slate-300">
        <span>Low attention</span>
        <div className="h-2 flex-1 rounded bg-gradient-to-r from-red-500 via-violet-500 to-blue-500" />
        <span>High attention</span>
        <InfoEyeTooltip
          ariaLabel="Pathology viewer attention legend explanation"
          content="This legend maps relative attention intensity within the current slide and settings: left (red) indicates lower model attention, right (blue) indicates higher attention. It is not an absolute probability scale and should not be compared across different models or sensitivity values without caution. Always interpret colors alongside evidence tiles and quality-control context."
        />
      </div>
    </div>
  );
}
