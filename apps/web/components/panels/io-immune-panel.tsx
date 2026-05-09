import { ContentCard } from "@/components/common/content-card";
import { PanelShell } from "@/components/common/panel-shell";
import type { IOImmuneScoreResponse } from "@/lib/api-client";

interface IOImmunePanelProps {
  ioScore: IOImmuneScoreResponse;
}

function asPercent(value: number | null): string {
  return value === null ? "N/A" : `${Math.round(value * 100)}%`;
}

const TIER_COLORS: Record<string, string> = {
  Hot: "text-red-300",
  Warm: "text-amber-300",
  Cold: "text-blue-300",
};

const TIER_BAR_COLORS: Record<string, string> = {
  Hot: "bg-red-400",
  Warm: "bg-amber-400",
  Cold: "bg-blue-400",
};

export function IOImmunePanel({ ioScore }: IOImmunePanelProps) {
  const tier = ioScore.tier ?? "Cold";
  const tierColor = TIER_COLORS[tier] ?? "text-slate-100";
  const barColor = TIER_BAR_COLORS[tier] ?? "bg-slate-400";

  return (
    <PanelShell
      title="IO Immune Score"
      subtitle="Tumor microenvironment hotness: Hot / Warm / Cold tier"
      meta={ioScore.meta}
    >
      {!ioScore.rna_available && (
        <div className="mb-3 rounded-lg border border-amber-400/50 bg-amber-500/10 p-3 text-xs text-amber-100">
          RNA modality missing — showing provisional WSI-only score (TIL fraction only).
        </div>
      )}

      <div className="grid gap-2 md:grid-cols-3">
        <ContentCard>
          <p className="text-xs text-slate-400">Tier</p>
          <p className={`mt-1 text-2xl font-bold ${tierColor}`}>{tier}</p>
        </ContentCard>
        <ContentCard>
          <p className="text-xs text-slate-400">Provisional (WSI)</p>
          <p className="mt-1 text-xl font-semibold text-slate-100">{asPercent(ioScore.provisional_score)}</p>
          <p className="mt-1 text-xs text-slate-400">TIL fraction only</p>
        </ContentCard>
        <ContentCard>
          <p className="text-xs text-slate-400">Refined (+ RNA)</p>
          <p className="mt-1 text-xl font-semibold text-slate-100">{asPercent(ioScore.refined_score)}</p>
          <p className="mt-1 text-xs text-slate-400">GEP / CYT / TIDE weighted</p>
        </ContentCard>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_1fr]">
        <ContentCard>
          <p className="text-xs font-semibold text-slate-300">Score components</p>
          <div className="mt-2 space-y-2">
            {ioScore.components.map((comp) => (
              <div key={comp.name}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className={comp.available ? "text-slate-200" : "text-slate-500"}>
                    {comp.name}
                    {!comp.available && <span className="ml-1 text-amber-400/70">(unavailable)</span>}
                  </span>
                  <span className="text-slate-400">
                    {comp.available && comp.value !== null ? asPercent(comp.value) : "—"}
                    <span className="ml-1 text-slate-500">w={comp.weight.toFixed(2)}</span>
                  </span>
                </div>
                <div className="h-1.5 rounded bg-slate-700">
                  {comp.available && comp.value !== null && (
                    <div
                      className={`h-1.5 rounded ${barColor}`}
                      style={{ width: `${Math.max(0, Math.min(100, comp.value * 100))}%` }}
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
        </ContentCard>

        <ContentCard>
          <p className="text-xs font-semibold text-slate-300">Interpretation</p>
          <div className="mt-2 space-y-2 text-xs text-slate-300">
            <div className="flex gap-2">
              <span className="font-semibold text-red-300">Hot ≥ 65%</span>
              <span>Inflamed TME — higher likelihood of IO benefit</span>
            </div>
            <div className="flex gap-2">
              <span className="font-semibold text-amber-300">Warm 40–65%</span>
              <span>Intermediate — IO benefit uncertain</span>
            </div>
            <div className="flex gap-2">
              <span className="font-semibold text-blue-300">Cold &lt; 40%</span>
              <span>Excluded/desert TME — IO less likely to respond</span>
            </div>
            {ioScore.missing_components.length > 0 && (
              <p className="mt-2 text-amber-200/70">
                Missing: {ioScore.missing_components.join(", ")}
              </p>
            )}
          </div>
          <p className="mt-3 text-[11px] text-slate-500">
            Research proxy only. Not for clinical decision-making.
          </p>
        </ContentCard>
      </div>

    </PanelShell>
  );
}
