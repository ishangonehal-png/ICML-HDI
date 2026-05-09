"use client";

import {
  useEffect,
  useId,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";

import { ContentCard } from "@/components/common/content-card";
import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import { MissingModalityState } from "@/components/common/missing-modality-state";
import { PanelShell } from "@/components/common/panel-shell";
import {
  apiClient,
  type ClinicalEligibilityResponse,
  type ClinicalPatientSummaryResponse,
  type ClinicalSurvivalBaselineResponse,
  type ClinicalTrialMatchResponse,
} from "@/lib/api-client";

interface ClinicalSummaryPanelProps {
  summary: ClinicalPatientSummaryResponse | null;
  eligibility: ClinicalEligibilityResponse | null;
  survival: ClinicalSurvivalBaselineResponse | null;
}

type TrialMatchLoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; payload: ClinicalTrialMatchResponse }
  | { status: "error"; message: string };

const TOOLTIP_COPY = {
  panelTitle:
    "Clinical summary panel consolidates extraction-derived patient context needed to ground multimodal interpretation. It provides normalized staging metadata, smoking history, trial context, and survival baseline proxies so reviewers can quickly orient before reading full documents. Use this panel to anchor narrative context, then verify critical details against provenance-linked records.",
  panelSubtitle:
    "The subtitle reflects this panel's role as the patient-context layer for the workspace. It should orient reviewers to structured baseline facts, not compete with pathology evidence or transcriptomic signal. Use it to frame the case before drilling into modality-specific panels.",
  panelMeta:
    "Clinical metadata shows which extraction pipeline release generated these normalized fields and when the transformation ran. This provenance is essential for reproducibility because schema updates, parsing fixes, or ontology remapping can shift reported values between runs. Compare metadata first whenever stage, eligibility, or survival outputs appear inconsistent across sessions.",
  panelProxyEstimate:
    "Proxy estimate marking indicates clinical-derived scores and buckets are exploratory outputs designed for research interpretation workflows. They summarize model and rules-engine behavior over extracted text, not clinician-validated adjudication. Keep decisions anchored in uncertainty, missingness, and raw report evidence rather than treating these condensed fields as definitive medical facts.",
  stage:
    "Stage is the normalized disease stage extracted from available clinical records and harmonized into a compact label for quick triage. It reflects reported extent at diagnosis, not an updated treatment-era restaging. Use this field as contextual orientation for comparing cases, then verify exact source wording through the cited clinical provenance snippets.",
  smokingStatus:
    "Smoking status is derived from structured clinical extraction and collapsed into a single cohort-friendly category. It captures documented tobacco exposure context that may shape baseline biology and outcome expectations, but it can be incomplete when source reports are sparse. Treat this value as metadata support, not a deterministic driver of score movement.",
  eligibilityProxy:
    "Matched trials (live) is pulled from a real-time ClinicalTrials.gov query using normalized diagnosis/stage/smoking context. It reflects current API results under this app's filters and ranking logic, not a static or hardcoded count. Always open the drawer to review trial-level rationale before taking action.",
  eligibilityCount:
    "Displayed count is the live ClinicalTrials.gov match count under current filters (default: recruiting-only). If unavailable, the panel shows an error state rather than falling back to a heuristic number.",
  survivalRiskGroup:
    "Risk group is a coarse bucket from the baseline survival proxy model that clusters cases into relative outcome strata within this research cohort. It is meant for comparative framing across similar records, not for individualized prognosis. Interpret alongside baseline months, uncertainty interval, and data completeness before drawing conclusions about biological severity or trajectory.",
  baselineMonths:
    "Baseline months represent the model's central proxy estimate of expected survival timescale under the current feature set. This number summarizes cohort-pattern signal, not observed patient follow-up and not treatment-adjusted prediction. Read it together with risk group and confidence interval to understand both center and uncertainty, especially when modality coverage is incomplete.",
  survivalCi:
    "Confidence interval provides an uncertainty band around the baseline months proxy, reflecting model variability and evidence strength for this case. Wider ranges imply weaker support or less consistent modality agreement, while narrower ranges indicate more stable internal signal. This remains exploratory uncertainty for research workflows, not a clinical confidence guarantee or counseling-grade estimate.",
  survivalBaseline:
    "Survival baseline combines coarse risk grouping, central months estimate, and uncertainty interval into a compact prognosis-proxy snapshot for comparative analysis. It is intended to contextualize case severity patterns within this dataset, not predict individual outcomes. Always review these values together with extraction completeness, modality coverage, and provenance before drawing downstream conclusions.",
} as const;

function MetricLabel({ label, tooltip }: { label: string; tooltip: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <p className="text-xs text-slate-400">{label}</p>
      <InfoEyeTooltip ariaLabel={`Clinical summary ${label} explanation`} content={tooltip} />
    </div>
  );
}

function formatTrialMatchCount(state: TrialMatchLoadState): {
  label: string;
  detail?: string;
} {
  if (state.status === "idle" || state.status === "loading") {
    return {
      label: "Loading…",
      detail: "Fetching live matched trial count from ClinicalTrials.gov.",
    };
  }

  if (state.status === "error") {
    return {
      label: "Unavailable",
      detail: state.message,
    };
  }

  const count = state.payload.trials.length;
  return {
    label: `${count} matched trial${count === 1 ? "" : "s"}`,
    detail: "Live count from ClinicalTrials.gov.",
  };
}

function sanitizeClinicalTrialsStudyUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      return null;
    }

    const hostname = parsed.hostname.toLowerCase();
    if (hostname !== "clinicaltrials.gov" && hostname !== "www.clinicaltrials.gov") {
      return null;
    }

    return parsed.toString();
  } catch {
    return null;
  }
}

export function ClinicalSummaryPanel({
  summary,
  eligibility,
  survival,
}: ClinicalSummaryPanelProps) {
  const [isTrialDrawerOpen, setIsTrialDrawerOpen] = useState(false);
  const [trialMatchState, setTrialMatchState] = useState<TrialMatchLoadState>({ status: "idle" });
  const trialMatchCount = formatTrialMatchCount(trialMatchState);
  const drawerTitleId = useId();

  const caseId = summary?.case_id ?? eligibility?.case_id ?? survival?.case_id ?? null;

  useEffect(() => {
    if (!isTrialDrawerOpen) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsTrialDrawerOpen(false);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isTrialDrawerOpen]);

  useEffect(() => {
    setTrialMatchState({ status: "idle" });
    setIsTrialDrawerOpen(false);
  }, [caseId]);

  useEffect(() => {
    if (!caseId) {
      return;
    }

    let cancelled = false;

    const preloadTrialCount = async () => {
      setTrialMatchState({ status: "loading" });

      try {
        const payload = await apiClient.getClinicalTrialMatches(caseId, {
          limit: 20,
          recruitingOnly: true,
        });

        if (cancelled) {
          return;
        }

        if (!payload.available) {
          setTrialMatchState({
            status: "error",
            message: payload.unavailable_reason ?? "Clinical trial matches unavailable for this case.",
          });
          return;
        }

        setTrialMatchState({ status: "success", payload });
      } catch (_error) {
        if (!cancelled) {
          setTrialMatchState({
            status: "error",
            message: "Unable to load live ClinicalTrials.gov matches.",
          });
        }
      }
    };

    void preloadTrialCount();

    return () => {
      cancelled = true;
    };
  }, [caseId]);

  const loadTrialMatches = async () => {
    if (!caseId) {
      setTrialMatchState({ status: "error", message: "Case ID unavailable for trial retrieval." });
      return;
    }

    if (trialMatchState.status === "success" && trialMatchState.payload.case_id === caseId) {
      return;
    }

    setTrialMatchState({ status: "loading" });

    try {
      const payload = await apiClient.getClinicalTrialMatches(caseId, {
        limit: 20,
        recruitingOnly: true,
      });

      if (!payload.available) {
        setTrialMatchState({
          status: "error",
          message: payload.unavailable_reason ?? "Clinical trial matches unavailable for this case.",
        });
        return;
      }

      setTrialMatchState({ status: "success", payload });
    } catch (_error) {
      setTrialMatchState({ status: "error", message: "Unable to load matched trials." });
    }
  };

  const openTrialDrawer = () => {
    setIsTrialDrawerOpen(true);
    void loadTrialMatches();
  };

  const onTrialCardClick = (event: ReactMouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest("button") || target.closest("a")) {
      return;
    }
    openTrialDrawer();
  };

  const onTrialCardKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) {
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openTrialDrawer();
    }
  };

  return (
    <>
      <PanelShell
        title="Clinical summary panel"
        subtitle="Structured patient context, live trial matches, and survival baseline"
        meta={summary?.meta}
        tooltips={{
          title: TOOLTIP_COPY.panelTitle,
          subtitle: TOOLTIP_COPY.panelSubtitle,
          meta: TOOLTIP_COPY.panelMeta,
          proxyEstimate: TOOLTIP_COPY.panelProxyEstimate,
        }}
      >
        {!summary && !survival && !caseId ? (
          <MissingModalityState
            modality="Clinical"
            description="Clinical documents unavailable. Eligibility and baseline fields remain hidden until extracted data is present."
          />
        ) : (
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            <ContentCard>
              <MetricLabel label="Stage" tooltip={TOOLTIP_COPY.stage} />
              <p className="mt-1 text-sm font-semibold text-slate-100">{summary?.stage ?? "N/A"}</p>
            </ContentCard>

            <ContentCard>
              <MetricLabel label="Smoking status" tooltip={TOOLTIP_COPY.smokingStatus} />
              <p className="mt-1 text-sm font-semibold text-slate-100">{summary?.smoking_status ?? "N/A"}</p>
            </ContentCard>

            <ContentCard>
              <div className="flex items-center gap-1.5">
                <p className="text-xs font-semibold text-slate-300">Survival baseline</p>
                <InfoEyeTooltip
                  ariaLabel="Clinical summary survival baseline explanation"
                  content={TOOLTIP_COPY.survivalBaseline}
                />
              </div>
              {survival ? (
                <div className="mt-2 space-y-1 text-xs text-slate-300">
                  <div className="flex items-center justify-between gap-2">
                    <MetricLabel label="Risk group" tooltip={TOOLTIP_COPY.survivalRiskGroup} />
                    <span>{survival.risk_group ?? "N/A"}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <MetricLabel label="Baseline months" tooltip={TOOLTIP_COPY.baselineMonths} />
                    <span>{survival.baseline_months !== null ? `${survival.baseline_months} mo` : "N/A"}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <MetricLabel label="Confidence interval (mo)" tooltip={TOOLTIP_COPY.survivalCi} />
                    <span>
                      {survival.confidence_interval
                        ? `${survival.confidence_interval[0]}–${survival.confidence_interval[1]} mo`
                        : "N/A"}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-xs text-slate-400">Survival baseline unavailable.</p>
              )}
            </ContentCard>

            <ContentCard
              role="button"
              tabIndex={0}
              aria-label="Open matched clinical trials"
              aria-haspopup="dialog"
              aria-expanded={isTrialDrawerOpen}
              onClick={onTrialCardClick}
              onKeyDown={onTrialCardKeyDown}
              className="cursor-pointer transition hover:border-cyan-300/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/70"
            >
              <MetricLabel label="Matched trials (live)" tooltip={TOOLTIP_COPY.eligibilityProxy} />
              <p className="mt-1 text-sm font-semibold text-slate-100">{trialMatchCount.label}</p>
              <div className="mt-1 flex items-start gap-1.5 text-[11px] text-slate-400">
                <p>{trialMatchCount.detail ?? "Live count from ClinicalTrials.gov."}</p>
                <InfoEyeTooltip ariaLabel="Clinical summary trial count semantics" content={TOOLTIP_COPY.eligibilityCount} />
              </div>
              <p className="mt-2 text-xs font-medium text-cyan-200">View matched trials</p>
            </ContentCard>
          </div>
        )}
      </PanelShell>

      {isTrialDrawerOpen ? (
        <div className="fixed inset-0 z-50" aria-hidden={false}>
          <button
            type="button"
            aria-label="Close matched trials panel"
            className="absolute inset-0 h-full w-full bg-slate-950/70"
            onClick={() => setIsTrialDrawerOpen(false)}
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-labelledby={drawerTitleId}
            className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col border-l border-shell-border bg-slate-950/95 p-4 text-slate-100 shadow-2xl"
          >
            <div className="flex items-center justify-between gap-2 border-b border-shell-border pb-3">
              <h3 id={drawerTitleId} className="text-sm font-semibold text-slate-100">
                Matched clinical trials
              </h3>
              <button
                type="button"
                className="rounded-md border border-shell-border px-2 py-1 text-xs text-slate-200 hover:border-cyan-300/70"
                onClick={() => setIsTrialDrawerOpen(false)}
                autoFocus
              >
                Close
              </button>
            </div>

            <div className="mt-3 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 text-sm">
              {trialMatchState.status === "loading" ? (
                <p className="text-xs text-slate-300">Loading trial matches from ClinicalTrials.gov…</p>
              ) : null}

              {trialMatchState.status === "error" ? (
                <div className="rounded-lg border border-amber-400/40 bg-amber-900/20 p-3 text-xs text-amber-100">
                  <p>{trialMatchState.message}</p>
                </div>
              ) : null}

              {trialMatchState.status === "success" && trialMatchState.payload.trials.length === 0 ? (
                <div className="rounded-lg border border-shell-border bg-shell-panel/60 p-3 text-xs text-slate-300">
                  <p>No matched trials returned for the current normalized feature profile.</p>
                </div>
              ) : null}

              {trialMatchState.status === "success" && trialMatchState.payload.trials.length > 0 ? (
                <>
                  <p className="text-xs text-slate-400">
                    Query terms: {trialMatchState.payload.query_terms.join(" · ")}
                  </p>
                  <ul className="space-y-2">
                    {trialMatchState.payload.trials.map((trial) => {
                      const safeStudyUrl = sanitizeClinicalTrialsStudyUrl(trial.study_url);

                      return (
                        <li key={trial.nct_id} className="rounded-lg border border-shell-border bg-shell-panel/60 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-sm font-semibold text-slate-100">{trial.title}</p>
                              <p className="mt-1 text-xs text-slate-300">
                                {trial.nct_id} · {trial.status}
                                {trial.phase ? ` · ${trial.phase}` : ""}
                              </p>
                            </div>
                            {safeStudyUrl ? (
                              <a
                                href={safeStudyUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="rounded-md border border-cyan-300/40 px-2 py-1 text-xs text-cyan-100 hover:border-cyan-200"
                                aria-label={`Open ${trial.nct_id} on ClinicalTrials.gov`}
                              >
                                Open
                              </a>
                            ) : (
                              <span
                                className="rounded-md border border-slate-600/60 px-2 py-1 text-xs text-slate-400"
                                aria-label={`${trial.nct_id} study link unavailable`}
                              >
                                Link unavailable
                              </span>
                            )}
                          </div>
                          <p className="mt-2 text-xs text-slate-300">{trial.rationale}</p>
                          {trial.match_reasons.length > 0 ? (
                            <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-400">
                              {trial.match_reasons.map((reason) => (
                                <li key={`${trial.nct_id}-${reason}`}>{reason}</li>
                              ))}
                            </ul>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </>
              ) : null}
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
