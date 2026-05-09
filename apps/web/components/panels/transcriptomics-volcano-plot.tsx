"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import type {
  TranscriptomicsDegVolcanoPlotConfig,
  TranscriptomicsDegVolcanoPoint,
} from "@/lib/api-client";

interface TranscriptomicsVolcanoPlotProps {
  points: TranscriptomicsDegVolcanoPoint[];
  plot: TranscriptomicsDegVolcanoPlotConfig;
}

interface PlotDomain {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

interface DragState {
  startX: number;
  startY: number;
  origin: PlotDomain;
}

const VIEW_WIDTH = 680;
const VIEW_HEIGHT = 360;
const PADDING = { top: 16, right: 20, bottom: 34, left: 44 };

const VOLCANO_AXES_TOOLTIP =
  "Each point encodes one gene: the x-axis is log2 fold-change proxy and the y-axis is -log10 p-value proxy. Dashed vertical guides mark ± fold-change threshold, while the dashed horizontal guide marks the significance cutoff. Genes beyond both guides are prioritized as stronger differential-expression candidates. Use this as exploratory ranking, not definitive statistics.";

const VOLCANO_SELECTED_GENE_TOOLTIP =
  "Selected-gene stats report the point currently clicked in the plot, including symbol, effect-size proxy, transformed significance, and an approximate p-value. These numbers come from the same endpoint payload rendered above, so they are ideal for rapid triage and hypothesis notes. They are not corrected inferential outputs and should be treated as directional evidence only.";

const VOLCANO_RETURNED_POINTS_TOOLTIP =
  "Returned-points summary shows how many genes were actually plotted versus total genes observed by the differential-expression endpoint. Downsampling or filter constraints can limit visible points for interaction performance, so this ratio communicates representativeness. If coverage is low, avoid overgeneralizing cluster shapes and validate candidate genes against the full exported results before downstream decisions.";

function extent(values: number[]): [number, number] {
  if (values.length === 0) {
    return [-2, 2];
  }

  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  if (minValue === maxValue) {
    return [minValue - 1, maxValue + 1];
  }

  return [minValue, maxValue];
}

function buildInitialDomain(points: TranscriptomicsDegVolcanoPoint[]): PlotDomain {
  const xValues = points.map((point) => point.x);
  const yValues = points.map((point) => point.y);

  const [xMinRaw, xMaxRaw] = extent(xValues);
  const [_, yMaxRaw] = extent(yValues);

  const xPadding = Math.max((xMaxRaw - xMinRaw) * 0.1, 0.4);
  const yMax = Math.max(yMaxRaw * 1.1, 2.5);

  return {
    xMin: xMinRaw - xPadding,
    xMax: xMaxRaw + xPadding,
    yMin: 0,
    yMax,
  };
}

function clampView(view: PlotDomain, full: PlotDomain): PlotDomain {
  const fullXRange = Math.max(full.xMax - full.xMin, 1e-6);
  const fullYRange = Math.max(full.yMax - full.yMin, 1e-6);

  const minXRange = fullXRange * 0.05;
  const minYRange = fullYRange * 0.05;

  let xRange = Math.max(Math.min(view.xMax - view.xMin, fullXRange), minXRange);
  let yRange = Math.max(Math.min(view.yMax - view.yMin, fullYRange), minYRange);

  let xMin = view.xMin;
  let yMin = view.yMin;

  if (xMin < full.xMin) {
    xMin = full.xMin;
  }
  if (xMin + xRange > full.xMax) {
    xMin = full.xMax - xRange;
  }

  if (yMin < full.yMin) {
    yMin = full.yMin;
  }
  if (yMin + yRange > full.yMax) {
    yMin = full.yMax - yRange;
  }

  return {
    xMin,
    xMax: xMin + xRange,
    yMin,
    yMax: yMin + yRange,
  };
}

export function TranscriptomicsVolcanoPlot({ points, plot }: TranscriptomicsVolcanoPlotProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  const fullDomain = useMemo(() => buildInitialDomain(points), [points]);
  const [view, setView] = useState<PlotDomain>(fullDomain);
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [selectedPointIndex, setSelectedPointIndex] = useState<number | null>(null);

  useEffect(() => {
    setView(fullDomain);
    setSelectedPointIndex(null);
  }, [fullDomain]);

  const selectedGene =
    selectedPointIndex !== null ? points[selectedPointIndex] ?? null : null;

  const plotWidth = VIEW_WIDTH - PADDING.left - PADDING.right;
  const plotHeight = VIEW_HEIGHT - PADDING.top - PADDING.bottom;

  const xScale = (value: number) =>
    PADDING.left + ((value - view.xMin) / Math.max(view.xMax - view.xMin, 1e-6)) * plotWidth;
  const yScale = (value: number) =>
    PADDING.top + ((view.yMax - value) / Math.max(view.yMax - view.yMin, 1e-6)) * plotHeight;

  const isWithinPlot = (x: number, y: number) =>
    x >= PADDING.left && x <= PADDING.left + plotWidth && y >= PADDING.top && y <= PADDING.top + plotHeight;

  const onWheel: React.WheelEventHandler<SVGSVGElement> = (event) => {
    event.preventDefault();

    const svg = svgRef.current;
    if (!svg) {
      return;
    }

    const rect = svg.getBoundingClientRect();
    const localX = event.clientX - rect.left;
    const localY = event.clientY - rect.top;

    if (!isWithinPlot(localX, localY)) {
      return;
    }

    const zoomFactor = event.deltaY > 0 ? 1.15 : 0.85;
    const currentXRange = view.xMax - view.xMin;
    const currentYRange = view.yMax - view.yMin;

    const nextXRange = currentXRange * zoomFactor;
    const nextYRange = currentYRange * zoomFactor;

    const xRatio = (localX - PADDING.left) / plotWidth;
    const yRatio = (localY - PADDING.top) / plotHeight;

    const cursorXValue = view.xMin + xRatio * currentXRange;
    const cursorYValue = view.yMax - yRatio * currentYRange;

    const nextView = {
      xMin: cursorXValue - xRatio * nextXRange,
      xMax: cursorXValue + (1 - xRatio) * nextXRange,
      yMin: cursorYValue - (1 - yRatio) * nextYRange,
      yMax: cursorYValue + yRatio * nextYRange,
    };

    setView(clampView(nextView, fullDomain));
  };

  const onMouseDown: React.MouseEventHandler<SVGSVGElement> = (event) => {
    const svg = svgRef.current;
    if (!svg) {
      return;
    }

    const rect = svg.getBoundingClientRect();
    const localX = event.clientX - rect.left;
    const localY = event.clientY - rect.top;
    if (!isWithinPlot(localX, localY)) {
      return;
    }

    setDragState({
      startX: event.clientX,
      startY: event.clientY,
      origin: view,
    });
  };

  const onMouseMove: React.MouseEventHandler<SVGSVGElement> = (event) => {
    if (!dragState) {
      return;
    }

    const dx = event.clientX - dragState.startX;
    const dy = event.clientY - dragState.startY;

    const xRange = dragState.origin.xMax - dragState.origin.xMin;
    const yRange = dragState.origin.yMax - dragState.origin.yMin;

    const xShift = -(dx / plotWidth) * xRange;
    const yShift = (dy / plotHeight) * yRange;

    const nextView = {
      xMin: dragState.origin.xMin + xShift,
      xMax: dragState.origin.xMax + xShift,
      yMin: dragState.origin.yMin + yShift,
      yMax: dragState.origin.yMax + yShift,
    };

    setView(clampView(nextView, fullDomain));
  };

  const stopDragging = () => {
    setDragState(null);
  };

  const xThresholdRight = xScale(plot.x_threshold_abs);
  const xThresholdLeft = xScale(-plot.x_threshold_abs);
  const yThreshold = yScale(plot.y_threshold);

  const selectedSummary = selectedGene
    ? `${selectedGene.gene_symbol} · log2FC proxy ${selectedGene.log2_fc_proxy.toFixed(2)} · -log10 p ${selectedGene.y.toFixed(2)} · p≈${selectedGene.p_value_proxy.toExponential(2)}`
    : "Click a point to inspect gene-level proxy statistics.";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 text-[11px] text-slate-300">
        <div className="flex items-center gap-1">
          <p>{plot.proxy_note}</p>
          <InfoEyeTooltip ariaLabel="Transcriptomics volcano plot axes and thresholds explanation" content={VOLCANO_AXES_TOOLTIP} />
        </div>
        <button
          type="button"
          onClick={() => setView(fullDomain)}
          className="rounded border border-shell-border bg-slate-900/50 px-2 py-1 text-[11px] text-slate-200 hover:border-cyan-300/70"
        >
          Reset view
        </button>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="h-[280px] w-full rounded border border-shell-border bg-slate-950/60"
        role="img"
        aria-label="Transcriptomics DEG volcano plot"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={stopDragging}
        onMouseLeave={stopDragging}
      >
        <rect
          x={PADDING.left}
          y={PADDING.top}
          width={plotWidth}
          height={plotHeight}
          fill="transparent"
          stroke="rgba(148, 163, 184, 0.25)"
        />

        <line
          x1={PADDING.left}
          x2={PADDING.left + plotWidth}
          y1={yScale(0)}
          y2={yScale(0)}
          stroke="rgba(148, 163, 184, 0.4)"
          strokeWidth={1}
        />

        <line
          x1={xThresholdLeft}
          x2={xThresholdLeft}
          y1={PADDING.top}
          y2={PADDING.top + plotHeight}
          stroke="rgba(250, 204, 21, 0.7)"
          strokeDasharray="4 4"
        />
        <line
          x1={xThresholdRight}
          x2={xThresholdRight}
          y1={PADDING.top}
          y2={PADDING.top + plotHeight}
          stroke="rgba(250, 204, 21, 0.7)"
          strokeDasharray="4 4"
        />
        <line
          x1={PADDING.left}
          x2={PADDING.left + plotWidth}
          y1={yThreshold}
          y2={yThreshold}
          stroke="rgba(250, 204, 21, 0.7)"
          strokeDasharray="4 4"
        />

        {points.map((point, pointIndex) => {
          const cx = xScale(point.x);
          const cy = yScale(point.y);
          const color = point.direction === "up"
            ? "rgba(248, 113, 113, 0.9)"
            : point.direction === "down"
              ? "rgba(96, 165, 250, 0.9)"
              : "rgba(148, 163, 184, 0.55)";

          if (!isWithinPlot(cx, cy)) {
            return null;
          }

          return (
            <circle
              key={`${point.gene_symbol}-${pointIndex}`}
              cx={cx}
              cy={cy}
              r={selectedPointIndex === pointIndex ? 4 : 2.2}
              fill={color}
              className="cursor-pointer"
              onClick={() => setSelectedPointIndex(pointIndex)}
            />
          );
        })}

        <text x={VIEW_WIDTH / 2} y={VIEW_HEIGHT - 8} fill="rgba(226, 232, 240, 0.9)" textAnchor="middle" fontSize="11">
          {plot.x_axis_label}
        </text>
        <text
          x={14}
          y={VIEW_HEIGHT / 2}
          fill="rgba(226, 232, 240, 0.9)"
          textAnchor="middle"
          fontSize="11"
          transform={`rotate(-90 14 ${VIEW_HEIGHT / 2})`}
        >
          {plot.y_axis_label}
        </text>
      </svg>

      <div className="rounded border border-shell-border bg-slate-900/40 px-3 py-2 text-xs text-slate-200">
        <div className="flex items-start gap-1">
          <p className="flex-1">{selectedSummary}</p>
          <InfoEyeTooltip
            ariaLabel="Transcriptomics selected volcano gene statistics explanation"
            content={VOLCANO_SELECTED_GENE_TOOLTIP}
            className="shrink-0"
          />
        </div>
        <div className="mt-1 flex items-start gap-1 text-[11px] text-slate-400">
          <p className="flex-1">
            {plot.returned_points} points shown of {plot.total_genes_observed} observed genes. Drag to pan, scroll to
            zoom.
          </p>
          <InfoEyeTooltip
            ariaLabel="Transcriptomics returned volcano points summary explanation"
            content={VOLCANO_RETURNED_POINTS_TOOLTIP}
            className="shrink-0"
          />
        </div>
      </div>
    </div>
  );
}
