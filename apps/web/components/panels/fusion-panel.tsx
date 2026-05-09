import { ContentCard } from "@/components/common/content-card";
import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import { PanelShell } from "@/components/common/panel-shell";
import type {
  FusionAttributionResponse,
  FusionScoreResponse,
  FusionSimilarCasesResponse,
} from "@/lib/api-client";

interface FusionPanelProps {
  score: FusionScoreResponse;
  attribution: FusionAttributionResponse;
  similar: FusionSimilarCasesResponse;
}

const TOOLTIP_COPY = {
  panelTitle:
    "Fusion panel aggregates modality outputs into one comparative endpoint view for this case. It is designed to help reviewers understand how pathology, clinical, and transcriptomic signals interact inside the current model version. Read this panel as a synthesis layer, then trace individual contributors in the upstream modality cards before deciding what drives movement.",
  panelSubtitle:
    "This subtitle highlights the core interpretation workflow: compare provisional baseline, refined estimate, confidence interval semantics, and attribution behavior in one place. The goal is to expose how adding RNA changes the combined signal and where agreement or conflict appears across modalities. It supports model debugging and cohort-level reasoning rather than direct treatment decision support.",
  panelMeta:
    "Fusion metadata records which fusion pipeline variant generated these outputs and when the run completed. Use it to confirm comparability before contrasting scores across cases or sessions. If method, version, or timestamp differ, treat value changes cautiously because they may reflect pipeline drift, fresh inputs, or updated preprocessing assumptions.",
  panelProxyEstimate:
    "The proxy estimate badge reminds users that fusion scores are exploratory research endpoints, not validated clinical probabilities. It communicates intent: useful for ranking patterns, understanding modality interaction, and generating hypotheses within this cohort. Keep interpretation bounded by uncertainty ranges, missing-modality states, and provenance links rather than using any single number in isolation.",
  provisional:
    "Provisional score is the fusion estimate produced from pathology and clinical features before transcriptomic integration. It acts as the fallback when RNA data is unavailable or fails quality criteria, preserving a comparable signal across cases. Interpret it as a relative research ranking cue inside this cohort, not as a calibrated patient-level probability.",
  refined:
    "Refined score extends the provisional baseline by incorporating RNA-derived evidence, including signature-level transcriptomic context when available. This value is typically preferred for interpretation because it captures broader multimodal agreement, but it still remains a proxy endpoint. Compare refined alongside provisional and delta to understand whether RNA meaningfully changes the inferred pattern.",
  delta:
    "Delta quantifies the change between provisional and refined estimates after RNA is applied. Positive deltas indicate transcriptomic evidence increased the fused signal, while negative deltas indicate attenuation relative to pathology-plus-clinical context. Magnitude is useful for diagnosing modality disagreement, but should be read as directional model behavior rather than a direct clinical effect-size statement.",
  confidenceInterval:
    "Confidence interval summarizes uncertainty around the active fusion endpoint (refined when RNA is applied, otherwise provisional fallback). Wider ranges indicate weaker support or higher disagreement across modality evidence; tighter ranges indicate more stable internal agreement. This range is a research-only uncertainty band and should not be treated as a clinical confidence guarantee.",
  confidenceIntervalEndpoint:
    "Endpoint semantics clarify which interval source is shown: refined_ci when RNA-applied mode is active, provisional_ci when fallback mode is used, or confidence_interval when the backend provides an already-resolved active endpoint band. Showing source prevents ambiguity about what uncertainty range actually wraps the displayed fusion estimate.",
  confidenceIntervalUnavailable:
    "This fallback appears when no confidence-interval payload was returned for the active endpoint in this run. Score values can still be displayed, but uncertainty remains under-specified and harder to compare across cases. Treat interpretation as lower-confidence exploratory output until a rerun provides explicit interval bounds and endpoint provenance.",
  rnaFallbackAlert:
    "This alert means RNA was requested but not used in fusion output for this case (missing or QC-rejected transcriptomics). The panel therefore emphasizes provisional behavior from pathology + clinical inputs, and refined-only metrics may remain unavailable. Treat this as a modality-coverage state, not as model failure.",
  modalityAttribution:
    "Modality attribution bars show each signal source's relative contribution weight in the final fusion estimate for this case. Higher percentages indicate stronger influence on the model output under current inputs, not standalone biological importance. Use these bars to debug agreement across pathology, clinical, and transcriptomics and to guide where deeper evidence inspection is most valuable.",
  modalityAttributionRow:
    "This row reports the modality's share of the fused endpoint for this case under the current run. It reflects relative model contribution, not independent biological effect size. Percentages are case-specific and may not sum to exactly 100% after rounding, so use them for directional weighting rather than strict arithmetic totals.",
  similarPatientRetrieval:
    "Similar patient retrieval surfaces nearest neighbors in the fused representation space so reviewers can compare this case against cohort patterns with related multimodal signatures. Retrieved notes provide lightweight context for why neighbors may align. Treat this as an exploratory analog search to generate hypotheses, then confirm using panel-level evidence and source-specific provenance.",
  similarDistance:
    "Distance measures how far each retrieved case sits from the index case in the shared embedding manifold used for similarity lookup. Smaller values imply closer representation-level alignment, while larger values indicate weaker match strength. Distance is model-space geometry, not direct clinical dissimilarity, so combine it with neighbor notes and endpoint-level evidence before interpretation.",
} as const;

function asPercent(value: number | null, options?: { signed?: boolean }): string {
  if (value === null) {
    return "N/A";
  }

  const rounded = Math.round(value * 100);
  if (options?.signed && rounded > 0) {
    return `+${rounded}%`;
  }

  return `${rounded}%`;
}

function asIntervalPercent(value: [number, number] | null): string {
  if (!value) {
    return "Unavailable";
  }

  const lower = Math.round(value[0] * 100);
  const upper = Math.round(value[1] * 100);

  if (!Number.isFinite(lower) || !Number.isFinite(upper)) {
    return "Unavailable";
  }

  return `${lower}% – ${upper}%`;
}

function normalizeConfidenceBounds(lower: unknown, upper: unknown): [number, number] | null {
  if (typeof lower !== "number" || typeof upper !== "number") {
    return null;
  }

  if (!Number.isFinite(lower) || !Number.isFinite(upper)) {
    return null;
  }

  return lower <= upper ? [lower, upper] : [upper, lower];
}

function normalizeConfidenceInterval(value: unknown): [number, number] | null {
  if (!Array.isArray(value) || value.length < 2) {
    return null;
  }

  return normalizeConfidenceBounds(value[0], value[1]);
}

function resolveFusionConfidenceInterval(score: FusionScoreResponse): {
  interval: [number, number] | null;
  sourceLabel: string;
} {
  const modeUsed = score.mode_used === "refined" ? "refined" : "provisional";

  const refinedCi = score.refined_ci
    ? normalizeConfidenceBounds(score.refined_ci.lower, score.refined_ci.upper)
    : null;
  const provisionalCi = score.provisional_ci
    ? normalizeConfidenceBounds(score.provisional_ci.lower, score.provisional_ci.upper)
    : null;
  const activeCi = normalizeConfidenceInterval(score.confidence_interval);

  if (modeUsed === "refined" && refinedCi) {
    return {
      interval: refinedCi,
      sourceLabel: "Endpoint: refined_ci (RNA-applied mode)",
    };
  }

  if (modeUsed === "provisional" && provisionalCi) {
    return {
      interval: provisionalCi,
      sourceLabel: "Endpoint: provisional_ci (fallback mode)",
    };
  }

  if (activeCi) {
    return {
      interval: activeCi,
      sourceLabel: `Endpoint: confidence_interval (${modeUsed} mode summary)`,
    };
  }

  if (modeUsed === "refined" && provisionalCi) {
    return {
      interval: provisionalCi,
      sourceLabel: "Endpoint fallback: provisional_ci (refined interval missing)",
    };
  }

  if (modeUsed === "provisional" && refinedCi) {
    return {
      interval: refinedCi,
      sourceLabel: "Endpoint fallback: refined_ci (provisional interval missing)",
    };
  }

  return {
    interval: null,
    sourceLabel: `Endpoint unavailable — ${modeUsed} interval not returned`,
  };
}

function modalityLabel(modality: "pathology" | "transcriptomics" | "clinical"): string {
  if (modality === "transcriptomics") {
    return "RNA";
  }
  return modality.charAt(0).toUpperCase() + modality.slice(1);
}

function MetricLabel({ label, tooltip }: { label: string; tooltip: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <p className="text-xs text-slate-400">{label}</p>
      <InfoEyeTooltip ariaLabel={`Fusion panel ${label} explanation`} content={tooltip} />
    </div>
  );
}

export function FusionPanel({ score, attribution, similar }: FusionPanelProps) {
  const hasRna =
    score.mode_used === "refined" ||
    score.rna_applied === true ||
    score.refined_score !== null ||
    !score.missing_modalities.includes("transcriptomics");
  const confidenceInterval = resolveFusionConfidenceInterval(score);

  return (
    <PanelShell
      title="Fusion panel"
      subtitle="Provisional/refined score story with CI semantics and modality attribution"
      meta={score.meta}
      tooltips={{
        title: TOOLTIP_COPY.panelTitle,
        subtitle: TOOLTIP_COPY.panelSubtitle,
        meta: TOOLTIP_COPY.panelMeta,
        proxyEstimate: TOOLTIP_COPY.panelProxyEstimate,
      }}
    >
      {!hasRna ? (
        <div className="mb-3 rounded-lg border border-amber-400/50 bg-amber-500/10 p-3 text-xs text-amber-100">
          <div className="flex items-start gap-1.5">
            <p>RNA not applied — fusion falls back to provisional estimate (pathology + clinical).</p>
            <InfoEyeTooltip ariaLabel="Fusion panel RNA fallback explanation" content={TOOLTIP_COPY.rnaFallbackAlert} />
          </div>
        </div>
      ) : null}

      <div className="grid gap-2 md:grid-cols-4">
        <ContentCard>
          <MetricLabel label="Provisional score" tooltip={TOOLTIP_COPY.provisional} />
          <p className="mt-1 text-xl font-semibold text-slate-100">{asPercent(score.provisional_score)}</p>
        </ContentCard>
        <ContentCard>
          <MetricLabel label="Refined score" tooltip={TOOLTIP_COPY.refined} />
          <p className="mt-1 text-xl font-semibold text-slate-100">{asPercent(score.refined_score)}</p>
        </ContentCard>
        <ContentCard>
          <MetricLabel label="Delta (RNA effect)" tooltip={TOOLTIP_COPY.delta} />
          <p className="mt-1 text-xl font-semibold text-slate-100">{asPercent(score.delta, { signed: true })}</p>
        </ContentCard>
        <ContentCard>
          <MetricLabel label="Confidence interval" tooltip={TOOLTIP_COPY.confidenceInterval} />
          <p className="mt-1 text-xl font-semibold text-slate-100">{asIntervalPercent(confidenceInterval.interval)}</p>
          <div className="mt-1 flex items-start gap-1.5 text-[11px] text-slate-400">
            <p>{confidenceInterval.sourceLabel}</p>
            <InfoEyeTooltip
              ariaLabel="Fusion panel confidence interval endpoint semantics"
              content={
                confidenceInterval.interval
                  ? TOOLTIP_COPY.confidenceIntervalEndpoint
                  : TOOLTIP_COPY.confidenceIntervalUnavailable
              }
            />
          </div>
        </ContentCard>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_1fr]">
        <ContentCard>
          <div className="flex items-center gap-1.5">
            <p className="text-xs font-semibold text-slate-300">Modality attribution bars</p>
            <InfoEyeTooltip
              ariaLabel="Fusion panel modality attribution bars explanation"
              content={TOOLTIP_COPY.modalityAttribution}
            />
          </div>
          <div className="mt-2 space-y-2">
            {attribution.contributions.map((row) => (
              <div key={row.modality}>
                <div className="mb-1 flex items-center justify-between text-xs text-slate-300">
                  <div className="flex items-center gap-1.5">
                    <span>{modalityLabel(row.modality)}</span>
                    <InfoEyeTooltip
                      ariaLabel={`Fusion panel ${modalityLabel(row.modality)} attribution semantics`}
                      content={TOOLTIP_COPY.modalityAttributionRow}
                    />
                  </div>
                  <span>{asPercent(row.contribution)}</span>
                </div>
                <div className="h-2 rounded bg-slate-700">
                  <div
                    className="h-2 rounded bg-cyan-400"
                    style={{ width: `${Math.max(0, Math.min(100, row.contribution * 100))}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </ContentCard>

        <ContentCard>
          <div className="flex items-center gap-1.5">
            <p className="text-xs font-semibold text-slate-300">Similar patient retrieval</p>
            <InfoEyeTooltip
              ariaLabel="Fusion panel similar patient retrieval explanation"
              content={TOOLTIP_COPY.similarPatientRetrieval}
            />
          </div>
          <div className="mt-1 flex items-center gap-1.5 text-[11px] text-slate-400">
            <p>Distance metric</p>
            <InfoEyeTooltip ariaLabel="Fusion panel similar patient distance explanation" content={TOOLTIP_COPY.similarDistance} />
          </div>
          {similar.similar_cases.length === 0 ? (
            <p className="mt-2 text-xs text-slate-400">No similar patient matches returned for this run.</p>
          ) : (
            <ul className="mt-2 space-y-2 text-xs text-slate-200">
              {similar.similar_cases.map((item) => (
                <li key={item.case_id} className="rounded-md border border-shell-border bg-slate-900/40 p-2">
                  <p className="font-medium">{item.case_id}</p>
                  <p className="text-slate-300">Distance: {item.distance.toFixed(2)}</p>
                  <p className="text-slate-300">{item.note}</p>
                </li>
              ))}
            </ul>
          )}
        </ContentCard>
      </div>
    </PanelShell>
  );
}
