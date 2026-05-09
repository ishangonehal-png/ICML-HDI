import { ContentCard } from "@/components/common/content-card";
import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import { PageSection } from "@/components/common/page-section";
import type {
  ClinicalPatientSummaryResponse,
  CohortCaseSummary,
  IOImmuneScoreResponse,
  IOSimilarCasesResponse,
} from "@/lib/api-client";

interface PatientHeaderProps {
  caseSummary: CohortCaseSummary;
  clinicalSummary?: ClinicalPatientSummaryResponse | null;
  ioImmuneScore?: IOImmuneScoreResponse;
  similarCases?: IOSimilarCasesResponse;
  similarCasesError?: string;
  loading?: boolean;
}

const TOOLTIP_COPY = {
  diagnosisStage:
    "Diagnosis and stage are the first orienting facts in the workspace. They come from extracted clinical summary fields when available and fall back to cohort metadata otherwise.",
  patientContext:
    "Patient context keeps age and smoking exposure visible at first glance because they shape interpretation of both prognosis and treatment fit.",
  ioReadiness:
    "This compresses the IO Immune score into a first-glance readiness summary. It shows the tier and whether the value is RNA-refined or provisional WSI-only.",
  similarPatients:
    "Most similar patients summarizes the nearest-neighbor retrieval result so the physician can immediately see whether there is cohort context for this case.",
  researchOnly:
    "This workspace is a research-only decision-support prototype. Top-line values summarize extracted and modeled signals, not validated clinical recommendations.",
} as const;

const TIER_STYLES: Record<string, string> = {
  Hot: "text-red-300",
  Warm: "text-amber-300",
  Cold: "text-blue-300",
};

function asPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "N/A" : `${Math.round(value * 100)}%`;
}

function formatAge(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : `Age ${Math.round(value)}`;
}

function joinParts(parts: Array<string | null | undefined>): string {
  return parts.filter((part): part is string => Boolean(part && part.trim())).join(" · ");
}

function derivePatientContext(clinicalSummary: ClinicalPatientSummaryResponse | null | undefined, caseSummary: CohortCaseSummary): {
  label: string;
  detail: string;
} {
  return {
    label: joinParts([
      formatAge(clinicalSummary?.age_at_diagnosis) ?? "Age N/A",
      clinicalSummary?.smoking_status ?? caseSummary.smoking_status ?? "Smoking N/A",
    ]),
    detail: "Clinical context",
  };
}

function deriveIOReadiness(ioImmuneScore: IOImmuneScoreResponse | undefined): { label: string; detail: string } {
  if (!ioImmuneScore) {
    return {
      label: "Unavailable",
      detail: "IO score not loaded",
    };
  }

  const tier = ioImmuneScore.tier ?? "N/A";
  const score = asPercent(ioImmuneScore.score);
  return {
    label: `${tier} · ${score}`,
    detail: ioImmuneScore.rna_available ? "RNA-refined score" : "WSI-only provisional score",
  };
}

function deriveSimilarPatients(
  similarCases: IOSimilarCasesResponse | undefined,
  similarCasesError?: string,
): { label: string; detail: string } {
  if (similarCasesError) {
    return {
      label: "Unavailable",
      detail: similarCasesError,
    };
  }

  const topNeighbor = similarCases?.neighbors?.[0];
  if (!topNeighbor) {
    return {
      label: "No similar cohort match",
      detail: "No neighbors returned for this case",
    };
  }

  return {
    label: `${asPercent(topNeighbor.similarity)} top-match similarity`,
    detail: joinParts([
      topNeighbor.case_id,
      topNeighbor.stage,
      topNeighbor.tier ? `${topNeighbor.tier} IO` : null,
    ]),
  };
}

function MetricLabel({ label, tooltip }: { label: string; tooltip: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <p className="text-xs text-slate-400">{label}</p>
      <InfoEyeTooltip ariaLabel={`Patient header ${label} explanation`} description={tooltip} />
    </div>
  );
}

function LoadingMetricCard({ label }: { label: string }) {
  return (
    <ContentCard>
      <p className="text-xs text-slate-400">{label}</p>
      <div className="mt-1 h-7 w-20 animate-pulse rounded bg-slate-700/60" />
    </ContentCard>
  );
}

export function PatientHeader({
  caseSummary,
  clinicalSummary,
  ioImmuneScore,
  similarCases,
  similarCasesError,
  loading = false,
}: PatientHeaderProps) {
  const diagnosis = clinicalSummary?.diagnosis ?? (loading ? "Diagnosis loading..." : "Diagnosis unavailable");
  const stage = clinicalSummary?.stage ?? caseSummary.stage ?? "Stage N/A";
  const contextLine = joinParts([
    caseSummary.case_id,
    formatAge(clinicalSummary?.age_at_diagnosis),
    clinicalSummary?.smoking_status ?? caseSummary.smoking_status,
  ]);
  const patientContext = derivePatientContext(clinicalSummary, caseSummary);
  const ioReadiness = deriveIOReadiness(ioImmuneScore);
  const similarPatientSummary = deriveSimilarPatients(similarCases, similarCasesError);
  const tier = ioImmuneScore?.tier ?? null;
  const ioTierStyle = tier ? (TIER_STYLES[tier] ?? "text-slate-100") : "text-slate-100";

  return (
    <PageSection className="bg-shell-panel/70">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-cyan-200/80">Patient workspace</p>
          <h1 className="text-xl font-semibold text-slate-100">{caseSummary.case_id}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-slate-300">
            <p>{joinParts([diagnosis, stage, contextLine])}</p>
            <InfoEyeTooltip
              ariaLabel="Patient header diagnosis, stage, and smoking status context"
              description={TOOLTIP_COPY.diagnosisStage}
            />
          </div>
        </div>

        <div className="rounded-lg border border-cyan-400/35 bg-cyan-950/30 px-3 py-2 text-xs text-cyan-100">
          <div className="flex items-center gap-1.5 font-semibold">
            <p>Research-only summary</p>
            <InfoEyeTooltip ariaLabel="Patient header research-only explanation" description={TOOLTIP_COPY.researchOnly} />
          </div>
          <p className="mt-1">
            {ioImmuneScore?.meta.version ?? "workspace-v1"} · {new Date(ioImmuneScore?.meta.timestamp ?? Date.now()).toLocaleString()}
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-2 text-sm md:grid-cols-4">
        {loading && !clinicalSummary && !ioImmuneScore ? (
          <>
            <LoadingMetricCard label="Diagnosis & stage" />
            <LoadingMetricCard label="Patient context" />
            <LoadingMetricCard label="IO readiness" />
            <LoadingMetricCard label="Most similar patients" />
          </>
        ) : (
          <>
            <ContentCard>
              <MetricLabel label="Diagnosis & stage" tooltip={TOOLTIP_COPY.diagnosisStage} />
              <p className="mt-1 text-base font-semibold text-slate-100">{joinParts([diagnosis, stage])}</p>
              <p className="mt-1 text-xs text-slate-400">{contextLine || "Clinical context limited"}</p>
            </ContentCard>

            <ContentCard>
              <MetricLabel label="Patient context" tooltip={TOOLTIP_COPY.patientContext} />
              <p className="mt-1 text-base font-semibold text-slate-100">{patientContext.label}</p>
              <p className="mt-1 text-xs text-slate-400">{patientContext.detail}</p>
            </ContentCard>

            <ContentCard>
              <MetricLabel label="IO readiness" tooltip={TOOLTIP_COPY.ioReadiness} />
              <p className={`mt-1 text-base font-semibold ${ioTierStyle}`}>{ioReadiness.label}</p>
              <p className="mt-1 text-xs text-slate-400">{ioReadiness.detail}</p>
            </ContentCard>

            <ContentCard>
              <MetricLabel label="Most similar patients" tooltip={TOOLTIP_COPY.similarPatients} />
              <p className="mt-1 text-base font-semibold text-slate-100">{similarPatientSummary.label}</p>
              <p className="mt-1 text-xs text-slate-400">{similarPatientSummary.detail}</p>
            </ContentCard>
          </>
        )}
      </div>
    </PageSection>
  );
}
