"use client";

import { useMemo, useRef, useState } from "react";

import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import type { TranscriptomicsMaPlotPoint } from "@/lib/api-client";

interface TranscriptomicsMaPlotProps {
  ma_plot: TranscriptomicsMaPlotPoint[];
}

const VIEW_WIDTH = 520;
const VIEW_HEIGHT = 320;
const PADDING = { top: 12, right: 16, bottom: 28, left: 40 };

const MA_AXES_TOOLTIP =
  "The MA plot compares average expression and change magnitude per gene. The x-axis is mean expression in log2 space, which helps separate low-count noise from stable signal. The y-axis is log2 fold-change, centered at zero for no directional shift. Highlighted points passed significance logic and are useful candidates for downstream interpretation.";

const MA_SELECTED_GENE_TOOLTIP =
  "When you click a dot, this readout reports the exact endpoint values for that gene: mean log2 expression and log2 fold-change, plus significance flag if present. Use it to confirm whether an outlier is both directionally large and supported at a stable expression level. Treat significance here as pipeline-specific prioritization, not a final statistical claim.";

function extent(values: number[]): [number, number] {
  if (values.length === 0) return [-1, 1];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return [min - 0.5, max + 0.5];
  const pad = (max - min) * 0.08 || 0.2;
  return [min - pad, max + pad];
}

export function TranscriptomicsMaPlot({ ma_plot }: TranscriptomicsMaPlotProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [selectedPointIndex, setSelectedPointIndex] = useState<number | null>(null);

  const xExtent = useMemo(
    () => extent(ma_plot.map((p) => p.mean_expr_log2)),
    [ma_plot],
  );
  const yExtent = useMemo(
    () => extent(ma_plot.map((p) => p.log2_fc)),
    [ma_plot],
  );

  const selected =
    selectedPointIndex !== null ? ma_plot[selectedPointIndex] ?? null : null;

  const plotWidth = VIEW_WIDTH - PADDING.left - PADDING.right;
  const plotHeight = VIEW_HEIGHT - PADDING.top - PADDING.bottom;
  const xScale = (v: number) =>
    PADDING.left + ((v - xExtent[0]) / (xExtent[1] - xExtent[0] || 1)) * plotWidth;
  const yScale = (v: number) =>
    PADDING.top + ((yExtent[1] - v) / (yExtent[1] - yExtent[0] || 1)) * plotHeight;

  const zeroY = yScale(0);

  const selectedSummary = selected
    ? `${selected.gene_symbol}: mean log₂ = ${selected.mean_expr_log2.toFixed(2)}, log₂ FC = ${selected.log2_fc.toFixed(2)}${selected.significant ? " (significant)" : ""}`
    : "Click a point to inspect gene-level MA statistics.";

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1">
        <p className="text-[11px] text-slate-400">
          Mean expression (log₂) vs log₂ fold-change. Significant genes highlighted.
        </p>
        <InfoEyeTooltip ariaLabel="Transcriptomics MA plot axes explanation" content={MA_AXES_TOOLTIP} />
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="h-[240px] w-full max-w-[520px] rounded border border-shell-border bg-slate-950/60"
        role="img"
        aria-label="Transcriptomics MA plot"
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
          y1={zeroY}
          y2={zeroY}
          stroke="rgba(148, 163, 184, 0.5)"
          strokeWidth={1}
        />
        {ma_plot.map((point, pointIndex) => {
          const cx = xScale(point.mean_expr_log2);
          const cy = yScale(point.log2_fc);
          const color = point.significant
            ? "rgba(248, 113, 113, 0.85)"
            : "rgba(148, 163, 184, 0.5)";
          const isSel = selectedPointIndex === pointIndex;
          return (
            <circle
              key={`${point.gene_symbol}-${pointIndex}`}
              cx={cx}
              cy={cy}
              r={isSel ? 4 : 2.5}
              fill={color}
              className="cursor-pointer"
              onClick={() => setSelectedPointIndex(pointIndex)}
            />
          );
        })}
        <text
          x={VIEW_WIDTH / 2}
          y={VIEW_HEIGHT - 6}
          fill="rgba(226, 232, 240, 0.9)"
          textAnchor="middle"
          fontSize="10"
        >
          Mean expression (log₂)
        </text>
        <text
          x={14}
          y={VIEW_HEIGHT / 2}
          fill="rgba(226, 232, 240, 0.9)"
          textAnchor="middle"
          fontSize="10"
          transform={`rotate(-90 14 ${VIEW_HEIGHT / 2})`}
        >
          log₂ FC
        </text>
      </svg>
      <div className="flex items-start gap-1">
        <p className="flex-1 text-xs text-slate-300">{selectedSummary}</p>
        <InfoEyeTooltip
          ariaLabel="Transcriptomics selected MA plot gene statistics explanation"
          content={MA_SELECTED_GENE_TOOLTIP}
          className="shrink-0"
        />
      </div>
    </div>
  );
}
