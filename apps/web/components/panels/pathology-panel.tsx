"use client";

import { useMemo, useState } from "react";

import { ContentCard } from "@/components/common/content-card";
import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import { MissingModalityState } from "@/components/common/missing-modality-state";
import { PanelShell } from "@/components/common/panel-shell";
import { EnsoPathologyViewer } from "@/components/panels/enso-pathology-viewer";
import type {
  ClinicalPatientSummaryResponse,
  PathologyEvidenceResponse,
  PathologyHeatmapResponse,
  PathologyTissueCompositionResponse,
} from "@/lib/api-client";

interface PathologyPanelProps {
  tissue: PathologyTissueCompositionResponse | null;
  heatmap: PathologyHeatmapResponse | null;
  evidence: PathologyEvidenceResponse | null;
  reportHighlights?: ClinicalPatientSummaryResponse["report_highlights"];
}

const TOOLTIP_COPY = {
  panelTitle:
    "Pathology panel is the image-first evidence workspace for this case. It combines slide-level attention, tissue composition summaries, and high-contributing tiles so reviewers can inspect what visual morphology likely influenced downstream fusion behavior. Use it to localize suspicious regions quickly, then validate interpretation with transcriptomic and clinical context before drawing broader conclusions.",
  panelSubtitle:
    "This subtitle outlines the three pathology evidence layers shown below: viewported heatmap context, tissue class fractions, and ranked tiles. Together they provide both global and local signal views so users can reconcile where model attention concentrates versus what tissue types are present. Treat the panel as interpretability support, not definitive histopathology annotation.",
  panelMeta:
    "Pathology metadata captures the exact image-analysis pipeline version and execution timestamp used to produce these visual artifacts. Confirm metadata before comparing slides across reruns, especially after preprocessing or model updates. Differences in method/version can shift tile ranking and composition estimates even when source slides are unchanged, so provenance checks are required for fair interpretation.",
  panelProxyEstimate:
    "Proxy estimate labeling indicates pathology outputs are model-derived exploratory signals intended for research workflows. Heatmaps and tile scores summarize relative contribution patterns rather than validated diagnostic findings. Use them to guide review and hypothesis generation, while keeping uncertainty explicit and corroborating claims with source images, quality flags, and complementary modality evidence.",
  slideId:
    "Slide id is the canonical key linking pathology endpoints for this case, including viewer tiles, tissue composition, heatmap artifacts, and evidence tiles. If slide id is unavailable, deep-zoom loading and endpoint cross-referencing become limited. Always confirm the slide id before comparing results across reruns or discussing tile-level findings with collaborators.",
  viewportHintUnavailable:
    "Viewport hint unavailable means the pathology heatmap payload did not provide a reproducible recommended camera box (x, y, w, h). You can still inspect the slide manually, but cross-review alignment is weaker because teammates may frame different regions. Treat interpretation as lower-confidence until a viewport hint is returned or an equivalent anchor is documented.",
  tissueCompositionUnavailable:
    "Tissue composition unavailable indicates the tissue-composition endpoint returned no fractions for this slide. Heatmap and tile evidence may still exist, but you lose the global class-balance context that helps explain where attention clusters. Interpret morphology hotspots more cautiously and avoid over-claiming tissue prevalence from local tiles alone.",
  evidenceTilesUnavailable:
    "No evidence tiles available means the ranked tile list is empty or missing for the selected pathology endpoint. Viewer overlays and tissue summaries can still support qualitative review, but you lose endpoint-ranked local rationales and bbox anchors for targeted replay. Treat this as reduced explainability coverage rather than a definitive absence of pathology signal.",
  reportHighlights:
    "Pathology report highlights are concise extracted lines from report text intended to speed orientation before detailed slide or note review. They summarize salient findings from the underlying document, not the whole panel. Use them as report-navigation aids and confirm important claims against the full pathology narrative.",
  viewportX:
    "x is the normalized left-origin coordinate of the suggested viewport_hint box. A value of 0 starts at the slide's far-left boundary, and 1 would align with the right edge before width is applied. Use x together with w to reproduce the same horizontal framing across sessions and machines.",
  viewportY:
    "y is the normalized top-origin coordinate of the viewport_hint box. A value of 0 anchors at the slide's top boundary, while larger values move the box downward. Read y with h when reconstructing the recommended field of view so review discussions reference the same vertical region consistently.",
  viewportW:
    "w is the normalized width of the viewport_hint box relative to total slide width. Smaller values indicate a tighter, zoomed-in recommendation; larger values preserve broader morphology context. Combine w with x to understand both placement and horizontal scope when comparing endpoint focus regions across cases.",
  viewportH:
    "h is the normalized height of the viewport_hint box relative to full slide height. Smaller values capture a narrower vertical window, while larger values include more surrounding tissue context. Interpret h alongside y to reconstruct the exact recommended review region and avoid inconsistent framing during cross-run comparisons.",
  tileIdScore:
    "Tile id is the stable patch identifier emitted by the pathology evidence endpoint for this slide. Score is a relative contribution weight under the active model/mode, not an absolute probability. Use tile ids to cross-reference overlays and logs, and use score primarily for within-slide ranking of influential regions.",
  tileRationale:
    "Rationale is an autogenerated textual summary describing visual cues that likely drove this tile's contribution score. It is a model-side interpretation aid, not a pathology-ground-truth annotation. Treat it as a hypothesis pointer, then validate the claim by inspecting morphology directly in the viewer and comparing neighboring evidence tiles.",
  tileBbox:
    "BBox status indicates whether normalized coordinates were returned for this tile so it can be projected as an overlay in the viewer. When unavailable, the tile can still inform ranking and rationale review, but spatial localization and exact region replay are limited for that specific evidence item.",
  selectedTileState:
    "Selected marks the currently active evidence tile that drives the viewer's evidence-box overlay and explanatory info-eyes in this panel. Switching selection changes which tile coordinates and rationale are emphasized for inspection. Use selection intentionally to keep discussion synchronized on the same local region when reviewing attention behavior.",
} as const;

export function PathologyPanel({
  tissue,
  heatmap,
  evidence,
  reportHighlights = [],
}: PathologyPanelProps) {
  const meta = tissue?.meta ?? heatmap?.meta ?? evidence?.meta;
  const slideId = heatmap?.slide_id ?? tissue?.slide_id ?? evidence?.slide_id ?? null;
  const hasPathologyData = Boolean(tissue || heatmap || evidence || reportHighlights.length > 0);

  const [selectedTileId, setSelectedTileId] = useState<string | null>(null);

  const activeTile = useMemo(() => {
    const tiles = evidence?.top_tiles ?? [];
    if (tiles.length === 0) {
      return null;
    }

    const selectedTile = selectedTileId ? tiles.find((tile) => tile.tile_id === selectedTileId) : null;
    return selectedTile ?? tiles[0];
  }, [evidence?.top_tiles, selectedTileId]);

  const isNestedInteractiveTarget = (
    target: EventTarget | null,
    currentTarget: EventTarget & HTMLDivElement,
  ) => {
    if (!(target instanceof Element)) {
      return false;
    }

    const nearestInteractiveElement = target.closest("button,a,input,select,textarea,[role='button']");
    return Boolean(nearestInteractiveElement && nearestInteractiveElement !== currentTarget);
  };

  return (
    <PanelShell
      title="Pathology panel"
      subtitle="WSI heatmap region, tissue composition, and top evidence tiles"
      meta={meta}
      tooltips={{
        title: TOOLTIP_COPY.panelTitle,
        subtitle: TOOLTIP_COPY.panelSubtitle,
        meta: TOOLTIP_COPY.panelMeta,
        proxyEstimate: TOOLTIP_COPY.panelProxyEstimate,
      }}
    >
      {!hasPathologyData ? (
        <MissingModalityState
          modality="Pathology"
          description="No WSI input detected for this case. Fusion uses available modalities with provisional labels."
        />
      ) : (
        <div className="space-y-3">
          {/* Pathology metric summary cards */}
          {tissue && (
            <div className="grid gap-2 md:grid-cols-5">
              {[
                {
                  label: "Tumor",
                  value: tissue.fractions.find((f) => f.tissue.toLowerCase() === "tumor")?.fraction ?? null,
                },
                {
                  label: "Stroma",
                  value: tissue.fractions.find((f) => f.tissue.toLowerCase() === "stroma")?.fraction ?? null,
                },
                {
                  label: "TIL",
                  value: tissue.fractions.find((f) => f.tissue.toLowerCase().includes("lymphocyte"))?.fraction ?? null,
                },
                {
                  label: "Necrosis",
                  value: tissue.fractions.find((f) => f.tissue.toLowerCase() === "necrosis")?.fraction ?? null,
                },
                {
                  label: "Top tile",
                  value: evidence?.top_tiles?.[0]?.score ?? null,
                },
              ].map((item) => (
                <ContentCard key={item.label}>
                  <p className="text-xs text-slate-400">{item.label}</p>
                  <p className="mt-1 text-lg font-semibold text-slate-100">
                    {item.value !== null ? `${Math.round(item.value * 100)}%` : "N/A"}
                  </p>
                </ContentCard>
              ))}
            </div>
          )}

          <div className="rounded-lg border border-shell-border bg-gradient-to-br from-cyan-900/25 to-emerald-900/10 p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Slide viewer</p>
                <InfoEyeTooltip
                  ariaLabel="Pathology panel slide viewer explanation"
                  content="This viewer centers the highest-signal pathology region for the selected slide and overlays model attention as a visual guide. It is intended for rapid triage, not pixel-perfect diagnosis. Pan and zoom to inspect context, then compare highlighted regions with evidence tiles and transcriptomic or clinical cards before interpreting any score."
                />
              </div>
              <div className="flex items-center gap-1 text-xs text-slate-300">
                <p>{slideId ?? "Slide id unavailable"}</p>
                <InfoEyeTooltip
                  ariaLabel="Pathology panel slide id explanation"
                  content={TOOLTIP_COPY.slideId}
                  align="end"
                />
              </div>
            </div>

            {slideId ? (
              <>
                <EnsoPathologyViewer
                  slideId={slideId}
                  className="mt-3"
                  viewportHint={heatmap?.viewport_hint ?? null}
                  selectedEvidenceBbox={activeTile?.bbox ?? null}
                  fallbackPreviewUrl={heatmap?.slide_preview_uri ?? null}
                  fallbackHeatmapUrl={heatmap?.heatmap_uri ?? null}
                />

                <div className="mt-3">
                  <div className="mb-2 flex items-center gap-1">
                    <p className="text-[11px] font-medium uppercase tracking-wide text-slate-300">Viewport hint values</p>
                    <InfoEyeTooltip
                      ariaLabel="Pathology panel viewport hint values explanation"
                      content="Viewport hint coordinates (x, y, w, h) are normalized fractions of the whole-slide image. They mark the recommended camera window where pathology signal is strongest. Values near 0 start at the top-left; values near 1 move toward the bottom-right. Use this box as a reproducible anchor when discussing cases across sessions."
                    />
                  </div>
                  <div className="grid gap-2 text-xs text-slate-200 sm:grid-cols-4">
                    {heatmap?.viewport_hint ? (
                      [
                        {
                          label: "x",
                          value: heatmap.viewport_hint.x,
                          tooltip: TOOLTIP_COPY.viewportX,
                        },
                        {
                          label: "y",
                          value: heatmap.viewport_hint.y,
                          tooltip: TOOLTIP_COPY.viewportY,
                        },
                        {
                          label: "w",
                          value: heatmap.viewport_hint.width,
                          tooltip: TOOLTIP_COPY.viewportW,
                        },
                        {
                          label: "h",
                          value: heatmap.viewport_hint.height,
                          tooltip: TOOLTIP_COPY.viewportH,
                        },
                      ].map((entry) => (
                        <div key={entry.label} className="rounded border border-shell-border bg-slate-900/40 px-2 py-1">
                          <div className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-slate-400">
                            <span>{entry.label}</span>
                            <InfoEyeTooltip
                              ariaLabel={`Pathology panel viewport ${entry.label} explanation`}
                              content={entry.tooltip}
                              align="start"
                            />
                          </div>
                          <p className="mt-1 text-xs text-slate-100">{entry.value.toFixed(2)}</p>
                        </div>
                      ))
                    ) : (
                      <div className="flex items-center gap-1 rounded border border-shell-border bg-slate-900/40 px-2 py-1 sm:col-span-4">
                        <span>Viewport hint unavailable.</span>
                        <InfoEyeTooltip
                          ariaLabel="Pathology panel viewport hint unavailable explanation"
                          content={TOOLTIP_COPY.viewportHintUnavailable}
                          align="start"
                        />
                      </div>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className="mt-2 flex aspect-[16/10] items-center justify-center rounded-md border border-dashed border-cyan-300/50 bg-slate-900/55 text-center text-sm text-cyan-100">
                Slide id unavailable for deep-zoom viewer.
              </div>
            )}
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <ContentCard>
              <div className="flex items-center gap-1">
                <p className="text-xs font-semibold text-slate-300">Pathology report highlights</p>
                <InfoEyeTooltip
                  ariaLabel="Pathology panel report highlights explanation"
                  content={TOOLTIP_COPY.reportHighlights}
                />
              </div>
              {reportHighlights.length === 0 ? (
                <p className="mt-2 text-xs text-slate-400">No extracted pathology report highlights available.</p>
              ) : (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-300">
                  {reportHighlights.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}
            </ContentCard>

            <ContentCard>
              <div className="flex items-center gap-1">
                <p className="text-xs font-semibold text-slate-300">Tissue composition fractions</p>
                <InfoEyeTooltip
                  ariaLabel="Pathology panel tissue composition fractions explanation"
                  content="Fractions estimate how much of the analyzed tissue belongs to each detected class, such as tumor, stroma, necrosis, or immune-rich regions. They are aggregated from tile-level model outputs and help explain why heatmap attention clusters in specific areas. Interpret these values comparatively across cases, not as exact ground-truth histology percentages."
                />
              </div>
              {tissue ? (
                <>
                  <ul className="mt-2 space-y-2 text-sm">
                    {tissue.fractions.map((entry) => (
                      <li key={entry.tissue} className="flex items-center justify-between">
                        <span className="text-slate-200">{entry.tissue}</span>
                        <span className="text-slate-100">{Math.round(entry.fraction * 100)}%</span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3 flex items-center gap-1 text-xs text-slate-400">
                    <span>
                      Coverage {Math.round(tissue.qc.coverage * 100)}% · {tissue.qc.artifact_warning ?? "No major artifacts"}
                    </span>
                    <InfoEyeTooltip
                      ariaLabel="Pathology panel coverage and artifact warning explanation"
                      content="Coverage reports what portion of usable slide area passed preprocessing and entered the pathology pipeline. Lower coverage can reduce confidence because fewer informative tiles contribute to the endpoint. Artifact warnings flag blur, pen marks, folds, or staining anomalies that may distort attention maps and evidence ranking, so high-warning slides should be treated as lower-trust visual evidence."
                    />
                  </div>
                </>
              ) : (
                <div className="mt-2 flex items-center gap-1 text-xs text-slate-400">
                  <span>Tissue composition unavailable.</span>
                  <InfoEyeTooltip
                    ariaLabel="Pathology panel tissue composition unavailable explanation"
                    content={TOOLTIP_COPY.tissueCompositionUnavailable}
                    align="start"
                  />
                </div>
              )}
            </ContentCard>

            <ContentCard>
              <div className="flex items-center gap-1">
                <p className="text-xs font-semibold text-slate-300">Top evidence tiles</p>
                <InfoEyeTooltip
                  ariaLabel="Pathology panel top evidence tiles explanation"
                  content="Top evidence tiles are the highest-contributing image patches for the active pathology endpoint. Score reflects relative contribution strength within this slide, rationale summarizes the model's textual reasoning, and BBox indicates whether exact coordinates can be projected into the viewer. Select a tile to lock that region and inspect surrounding morphology in full-slide context."
                />
              </div>
              {evidence?.top_tiles?.length ? (
                <ul className="mt-2 space-y-2 text-xs text-slate-200">
                  {evidence.top_tiles.map((tile) => {
                    const isActiveTile = activeTile?.tile_id === tile.tile_id;

                    return (
                      <li key={tile.tile_id}>
                        <div
                          role="button"
                          tabIndex={0}
                          aria-pressed={isActiveTile}
                          onClick={(event) => {
                            if (isNestedInteractiveTarget(event.target, event.currentTarget)) {
                              return;
                            }
                            setSelectedTileId(tile.tile_id);
                          }}
                          onKeyDown={(event) => {
                            if (event.target !== event.currentTarget) {
                              return;
                            }

                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelectedTileId(tile.tile_id);
                            }
                          }}
                          className={`w-full rounded-md border p-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/80 ${
                            isActiveTile
                              ? "border-cyan-300 bg-cyan-900/30"
                              : "border-shell-border bg-slate-900/40 hover:border-cyan-300/60"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1">
                              <p className="font-medium">
                                {tile.tile_id} · {Math.round(tile.score * 100)}%
                              </p>
                              {isActiveTile ? (
                                <InfoEyeTooltip ariaLabel="Pathology panel tile id and score explanation" content={TOOLTIP_COPY.tileIdScore} />
                              ) : null}
                            </div>
                            {isActiveTile ? (
                              <div className="flex items-center gap-1">
                                <span className="rounded border border-cyan-300/60 bg-cyan-900/35 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-cyan-100">
                                  Selected
                                </span>
                                <InfoEyeTooltip
                                  ariaLabel="Pathology panel selected tile state explanation"
                                  content={TOOLTIP_COPY.selectedTileState}
                                  align="end"
                                />
                              </div>
                            ) : null}
                          </div>
                          <div className="mt-1 flex items-start gap-1">
                            <p className="text-slate-300">{tile.rationale}</p>
                            {isActiveTile ? (
                              <InfoEyeTooltip ariaLabel="Pathology panel tile rationale explanation" content={TOOLTIP_COPY.tileRationale} />
                            ) : null}
                          </div>
                          <div className="mt-2 flex items-center gap-1 text-[11px] uppercase tracking-wide text-slate-400">
                            <span>{tile.bbox ? "BBox available" : "No bbox available"}</span>
                            {isActiveTile ? (
                              <InfoEyeTooltip ariaLabel="Pathology panel tile bbox status explanation" content={TOOLTIP_COPY.tileBbox} />
                            ) : null}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <div className="mt-2 flex items-center gap-1 text-xs text-slate-400">
                  <span>No evidence tiles available.</span>
                  <InfoEyeTooltip
                    ariaLabel="Pathology panel evidence tiles unavailable explanation"
                    content={TOOLTIP_COPY.evidenceTilesUnavailable}
                    align="start"
                  />
                </div>
              )}
            </ContentCard>
          </div>
        </div>
      )}
    </PanelShell>
  );
}
