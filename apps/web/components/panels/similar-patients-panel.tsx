import { ContentCard } from "@/components/common/content-card";
import { PanelShell } from "@/components/common/panel-shell";
import type { IOSimilarCase, IOSimilarCasesResponse } from "@/lib/api-client";

interface SimilarPatientsPanelProps {
  similarCases?: IOSimilarCasesResponse | null;
  errorMessage?: string;
}

function asPercent(value: number | null): string {
  return value === null ? "N/A" : `${Math.round(value * 100)}%`;
}

const TIER_BADGE_COLORS: Record<string, string> = {
  Hot: "bg-red-500/20 text-red-300 border border-red-500/30",
  Warm: "bg-amber-500/20 text-amber-300 border border-amber-500/30",
  Cold: "bg-blue-500/20 text-blue-300 border border-blue-500/30",
};

function SimilarCaseCard({ neighbor }: { neighbor: IOSimilarCase }) {
  const tier = neighbor.tier ?? "Cold";
  const badgeColor = TIER_BADGE_COLORS[tier] ?? "bg-slate-700 text-slate-300";

  return (
    <div className="flex items-start gap-3 rounded-lg border border-slate-700/50 bg-slate-800/50 p-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-xs font-mono text-slate-200">{neighbor.case_id}</span>
          {neighbor.tier && (
            <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${badgeColor}`}>
              {tier}
            </span>
          )}
          {neighbor.stage && (
            <span className="shrink-0 text-[10px] text-slate-400">{neighbor.stage}</span>
          )}
        </div>
        {(neighbor.age_at_diagnosis !== null || neighbor.smoking) && (
          <p className="mt-0.5 text-[10px] text-slate-500">
            {[
              neighbor.age_at_diagnosis !== null ? `Age ${Math.round(neighbor.age_at_diagnosis)}y` : null,
              neighbor.smoking,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        )}
        <p className="mt-0.5 text-[11px] text-slate-400">{neighbor.rationale}</p>
      </div>
      <div className="shrink-0 text-right">
        <p className="text-xs font-semibold text-slate-200">{asPercent(neighbor.similarity)}</p>
        <p className="text-[10px] text-slate-500">sim</p>
        <div className="mt-1 h-1 w-14 rounded bg-slate-700">
          <div
            className="h-1 rounded bg-slate-400"
            style={{ width: `${Math.round(neighbor.similarity * 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
}

export function SimilarPatientsPanel({ similarCases, errorMessage }: SimilarPatientsPanelProps) {
  return (
    <PanelShell
      title="Similar Patients"
      subtitle="Nearest-neighbor cohort retrieval across immune, RNA, stage, and demographics"
      meta={similarCases?.meta}
    >
      {errorMessage ? (
        <ContentCard>
          <p className="text-xs font-semibold text-slate-300">Retrieval status</p>
          <p className="mt-2 text-xs text-amber-200">{errorMessage}</p>
        </ContentCard>
      ) : similarCases && similarCases.neighbors.length > 0 ? (
        <ContentCard>
          <div className="mb-2 flex items-baseline justify-between">
            <p className="text-xs font-semibold text-slate-300">Nearest neighbors</p>
            <p className="text-[10px] text-slate-500">
              k-NN · {similarCases.feature_space.join(", ")} · n={similarCases.cohort_size}
            </p>
          </div>
          <div className="space-y-2">
            {similarCases.neighbors.map((neighbor) => (
              <SimilarCaseCard key={neighbor.case_id} neighbor={neighbor} />
            ))}
          </div>
        </ContentCard>
      ) : similarCases ? (
        <ContentCard>
          <p className="text-xs font-semibold text-slate-300">Retrieval status</p>
          <p className="mt-2 text-xs text-slate-400">No similar patients were returned for this case.</p>
        </ContentCard>
      ) : (
        <ContentCard>
          <p className="text-xs font-semibold text-slate-300">Retrieval status</p>
          <p className="mt-2 text-xs text-slate-400">Similar-patient retrieval has not loaded yet.</p>
        </ContentCard>
      )}
    </PanelShell>
  );
}
