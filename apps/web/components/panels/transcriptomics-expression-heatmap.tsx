"use client";

import { useMemo } from "react";

import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import type { TranscriptomicsExpressionHeatmap as TranscriptomicsExpressionHeatmapType } from "@/lib/api-client";

interface TranscriptomicsExpressionHeatmapProps {
  expression_heatmap: TranscriptomicsExpressionHeatmapType;
}

const CELL_HEIGHT = 24;
const CELL_MIN_WIDTH = 48;
const ROW_LABEL_WIDTH = 120;

const HEATMAP_VALUES_TOOLTIP =
  "Each heatmap cell shows normalized expression for one gene-row pair, with printed numbers preserving exact value context. Color intensity is scaled within this case from the observed minimum to maximum, so range is relative rather than cross-cohort absolute. Use the displayed range summary to interpret whether high-intensity cells represent subtle or large within-sample separation.";

const HEATMAP_RANGE_TOOLTIP =
  "Range reports the minimum and maximum normalized expression values present in the currently displayed matrix. This is the same interval used for color scaling, so it defines what the darkest and lightest cells mean in this view. Because scaling is case-local, compare patterns within this panel first and normalize externally before cross-case conclusions.";

function colorForValue(value: number, min: number, max: number): string {
  if (min === max) return "rgba(56, 189, 248, 0.5)";
  const t = (value - min) / (max - min);
  const r = Math.round(56 + (248 - 56) * t);
  const g = Math.round(189 - 80 * t);
  const b = Math.round(248 - 48 * t);
  return `rgb(${r},${g},${b})`;
}

export function TranscriptomicsExpressionHeatmap({
  expression_heatmap,
}: TranscriptomicsExpressionHeatmapProps) {
  const { gene_symbols, rows, available } = expression_heatmap;

  const { minVal, maxVal } = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const row of rows) {
      for (const v of row.values) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    if (min === Infinity) min = 0;
    if (max === -Infinity) max = 1;
    return { minVal: min, maxVal: max };
  }, [rows]);

  if (!available || rows.length === 0 || gene_symbols.length === 0) {
    return (
      <p className="text-xs text-slate-400">
        Expression heatmap not available for this case.
      </p>
    );
  }

  const cellWidth = Math.max(CELL_MIN_WIDTH, Math.min(80, 400 / gene_symbols.length));
  const totalWidth = ROW_LABEL_WIDTH + gene_symbols.length * cellWidth;

  return (
    <div className="space-y-2 overflow-x-auto">
      <div className="flex items-center gap-1">
        <p className="text-[11px] text-slate-400">
          Gene expression (normalized) across samples/rows.
        </p>
        <InfoEyeTooltip ariaLabel="Transcriptomics expression heatmap values and range explanation" content={HEATMAP_VALUES_TOOLTIP} />
      </div>
      <div
        className="rounded border border-shell-border bg-slate-950/60 font-mono text-[10px]"
        style={{ width: totalWidth, minWidth: 280 }}
      >
        <div className="flex border-b border-shell-border bg-slate-900/60">
          <div
            className="flex shrink-0 items-center border-r border-shell-border px-2 py-1.5 text-slate-400"
            style={{ width: ROW_LABEL_WIDTH }}
          >
            Sample / Row
          </div>
          <div className="flex">
            {gene_symbols.map((sym) => (
              <div
                key={sym}
                className="flex shrink-0 items-center justify-center border-r border-shell-border/50 py-1 text-slate-300"
                style={{ width: cellWidth }}
              >
                {sym}
              </div>
            ))}
          </div>
        </div>
        {rows.map((row, i) => (
          <div key={row.label} className="flex border-b border-shell-border/50 last:border-b-0">
            <div
              className="flex shrink-0 items-center truncate border-r border-shell-border px-2 py-1 text-slate-300"
              style={{ width: ROW_LABEL_WIDTH }}
              title={row.label}
            >
              {row.label}
            </div>
            <div className="flex">
              {row.values.map((val, j) => (
                <div
                  key={`${i}-${j}`}
                  className="flex shrink-0 items-center justify-center border-r border-shell-border/30 text-slate-100"
                  style={{
                    width: cellWidth,
                    height: CELL_HEIGHT,
                    backgroundColor: colorForValue(val, minVal, maxVal),
                  }}
                  title={`${gene_symbols[j]}: ${val.toFixed(2)}`}
                >
                  {val.toFixed(1)}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-1 text-[10px] text-slate-500">
        <p>
          Range: {minVal.toFixed(2)} – {maxVal.toFixed(2)}
        </p>
        <InfoEyeTooltip
          ariaLabel="Transcriptomics expression heatmap range semantics explanation"
          content={HEATMAP_RANGE_TOOLTIP}
          className="shrink-0"
        />
      </div>
    </div>
  );
}
