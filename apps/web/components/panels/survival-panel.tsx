import { ContentCard } from "@/components/common/content-card";
import { PanelShell } from "@/components/common/panel-shell";
import type { ClinicalSurvivalMlpResponse } from "@/lib/api-client";

interface SurvivalPanelProps {
  survivalMlp: ClinicalSurvivalMlpResponse;
}

function asPercent(value: number | null): string {
  return value === null ? "N/A" : `${Math.round(value * 100)}%`;
}

// ─── Panel ────────────────────────────────────────────────────────────────────
export function SurvivalPanel({ survivalMlp }: SurvivalPanelProps) {
  if (!survivalMlp.available) {
    return (
      <PanelShell
        title="Survival Analysis"
        subtitle="Survival MLP (pathology + RNA + metadata)"
        meta={survivalMlp.meta}
      >
        <p className="text-xs text-slate-400">
          {survivalMlp.unavailable_reason ?? "Survival MLP unavailable for this case."}
        </p>
        {survivalMlp.error_code ? (
          <p className="mt-2 font-mono text-[10px] text-slate-500" title="Error code for debugging">
            Code: {survivalMlp.error_code}
          </p>
        ) : null}
      </PanelShell>
    );
  }

  const predictionLabel =
    survivalMlp.predicted_class === 1 ? "Survived" : survivalMlp.predicted_class === 0 ? "Not survived" : "—";
  const horizonLabel =
    survivalMlp.horizon_years != null ? `${survivalMlp.horizon_years}-year` : "";

  return (
    <PanelShell
      title="Survival Analysis"
      subtitle={
        horizonLabel
          ? `Survival MLP · ${horizonLabel} horizon (pathology + RNA + metadata)`
          : "Survival MLP (pathology + RNA + metadata)"
      }
      meta={survivalMlp.meta}
    >
      <div className="grid gap-2 md:grid-cols-2">
        <ContentCard>
          <p className="text-xs text-slate-400">Prediction</p>
          <p className="mt-1 text-xl font-semibold text-slate-100">{predictionLabel}</p>
        </ContentCard>
        <ContentCard>
          <p className="text-xs text-slate-400">Confidence</p>
          <p className="mt-1 text-xl font-semibold text-slate-100">
            P(survived) = {asPercent(survivalMlp.probability)}
          </p>
        </ContentCard>
      </div>
      <p className="mt-3 text-[10px] text-slate-500">
        Research only. Not for clinical decision-making.
      </p>
    </PanelShell>
  );
}
