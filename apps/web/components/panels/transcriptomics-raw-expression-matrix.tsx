"use client";

import { useEffect, useMemo, useState } from "react";

import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import type {
  TranscriptomicsRawExpressionMatrixPreview,
  TranscriptomicsRawExpressionMatrixRow,
} from "@/lib/api-client";

interface TranscriptomicsRawExpressionMatrixProps {
  preview: TranscriptomicsRawExpressionMatrixPreview;
}

const RAW_MATRIX_TABLE_TOOLTIP =
  "This chart is a bounded preview of raw gene-expression matrix values from RNA input. It is intentionally truncated for UI performance and should be treated as directional evidence rather than a complete matrix export.";

const RAW_MATRIX_DETAILS_TOOLTIP =
  "Hover a row to inspect details quickly or click to pin selection while filtering. Values are taken directly from the raw-expression preview payload, with log2 transform shown for easier relative comparison.";

function formatValue(value: number): string {
  return Number.isFinite(value) ? value.toFixed(3) : "N/A";
}

export function TranscriptomicsRawExpressionMatrix({
  preview,
}: TranscriptomicsRawExpressionMatrixProps) {
  const [query, setQuery] = useState("");
  const [selectedGeneSymbol, setSelectedGeneSymbol] = useState<string | null>(null);
  const [hoveredGeneSymbol, setHoveredGeneSymbol] = useState<string | null>(null);

  const filteredRows = useMemo(() => {
    const normalized = query.trim().toUpperCase();
    if (!normalized) {
      return preview.rows;
    }
    return preview.rows.filter((row) => row.gene_symbol.includes(normalized));
  }, [preview.rows, query]);

  useEffect(() => {
    if (filteredRows.length === 0) {
      setSelectedGeneSymbol(null);
      return;
    }

    if (selectedGeneSymbol && filteredRows.some((row) => row.gene_symbol === selectedGeneSymbol)) {
      return;
    }

    setSelectedGeneSymbol(filteredRows[0].gene_symbol);
  }, [filteredRows, selectedGeneSymbol]);

  const activeRow: TranscriptomicsRawExpressionMatrixRow | null = useMemo(() => {
    const activeSymbol = hoveredGeneSymbol ?? selectedGeneSymbol;
    if (!activeSymbol) {
      return filteredRows[0] ?? null;
    }
    return filteredRows.find((row) => row.gene_symbol === activeSymbol) ?? filteredRows[0] ?? null;
  }, [filteredRows, hoveredGeneSymbol, selectedGeneSymbol]);

  if (!preview.available) {
    return (
      <p className="text-xs text-slate-400">
        {preview.unavailable_reason ?? "Raw matrix preview unavailable for this case."}
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-300">
        <div className="flex items-center gap-1">
          <p>Preview of raw matrix values (bounded for performance).</p>
          <InfoEyeTooltip
            ariaLabel="Transcriptomics raw matrix preview semantics explanation"
            content={RAW_MATRIX_TABLE_TOOLTIP}
          />
        </div>
        <p className="text-slate-400">
          Showing {filteredRows.length} filtered row(s), {preview.returned_rows} preview row(s),{" "}
          {preview.total_genes_observed} observed gene(s)
        </p>
      </div>

      <label className="block text-xs text-slate-300">
        <span className="mb-1 block">Search by gene symbol</span>
        <input
          aria-label="Search raw matrix preview by gene symbol"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter by gene symbol (e.g., CXCL9)"
          className="w-full rounded border border-shell-border bg-slate-950/70 px-2 py-1.5 text-xs text-slate-100 outline-none ring-cyan-300/50 placeholder:text-slate-500 focus:ring-1"
        />
      </label>

      <div className="max-h-64 overflow-auto rounded border border-shell-border bg-slate-950/60">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-slate-900/90 text-slate-300">
            <tr>
              <th className="px-2 py-1 text-left font-medium">Gene</th>
              <th className="px-2 py-1 text-right font-medium">Raw value</th>
              <th className="px-2 py-1 text-right font-medium">log2(raw + 1)</th>
              <th className="px-2 py-1 text-right font-medium">Rank</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-2 py-3 text-center text-slate-400">
                  No genes match this filter.
                </td>
              </tr>
            ) : (
              filteredRows.map((row) => {
                const isSelected = row.gene_symbol === selectedGeneSymbol;
                return (
                  <tr
                    key={row.gene_symbol}
                    tabIndex={0}
                    aria-selected={isSelected}
                    onClick={() => setSelectedGeneSymbol(row.gene_symbol)}
                    onMouseEnter={() => setHoveredGeneSymbol(row.gene_symbol)}
                    onMouseLeave={() => setHoveredGeneSymbol(null)}
                    onFocus={() => setHoveredGeneSymbol(row.gene_symbol)}
                    onBlur={() => setHoveredGeneSymbol(null)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedGeneSymbol(row.gene_symbol);
                      }
                    }}
                    className={
                      isSelected
                        ? "cursor-pointer border-t border-shell-border/30 bg-cyan-500/10 text-cyan-100 outline-none"
                        : "cursor-pointer border-t border-shell-border/30 text-slate-200 outline-none hover:bg-slate-800/50 focus:bg-slate-800/50"
                    }
                    data-testid={`raw-matrix-row-${row.gene_symbol}`}
                  >
                    <td className="px-2 py-1 font-medium">{row.gene_symbol}</td>
                    <td className="px-2 py-1 text-right">{formatValue(row.raw_value)}</td>
                    <td className="px-2 py-1 text-right">{formatValue(row.normalized_log2)}</td>
                    <td className="px-2 py-1 text-right">#{row.rank}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="rounded border border-shell-border bg-slate-900/50 p-2 text-xs text-slate-300">
        <div className="mb-1 flex items-center gap-1">
          <p className="font-medium text-slate-100">Row details</p>
          <InfoEyeTooltip
            ariaLabel="Transcriptomics raw matrix row details explanation"
            content={RAW_MATRIX_DETAILS_TOOLTIP}
          />
        </div>
        {activeRow ? (
          <p>
            {activeRow.gene_symbol} | raw {formatValue(activeRow.raw_value)} | log2(raw + 1){" "}
            {formatValue(activeRow.normalized_log2)} | rank #{activeRow.rank}
          </p>
        ) : (
          <p>No row selected.</p>
        )}
      </div>
    </div>
  );
}
