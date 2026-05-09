"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { PageSection } from "@/components/common/page-section";
import { apiClient, type CohortCaseSummary } from "@/lib/api-client";

interface UploadShellProps {
  cases: CohortCaseSummary[];
  initialCaseId?: string;
}

function resolveInitialCaseId(cases: CohortCaseSummary[], initialCaseId?: string): string {
  if (initialCaseId && cases.some((entry) => entry.case_id === initialCaseId)) {
    return initialCaseId;
  }

  return cases[0]?.case_id ?? "";
}

export function UploadShell({ cases, initialCaseId }: UploadShellProps) {
  const router = useRouter();
  const [selectedCaseId, setSelectedCaseId] = useState(() =>
    resolveInitialCaseId(cases, initialCaseId),
  );
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedCase = useMemo(
    () => cases.find((entry) => entry.case_id === selectedCaseId) ?? cases[0],
    [cases, selectedCaseId],
  );

  useEffect(() => {
    setSelectedCaseId((current) => {
      if (current && cases.some((entry) => entry.case_id === current)) {
        return current;
      }
      return resolveInitialCaseId(cases, initialCaseId);
    });
  }, [cases, initialCaseId]);

  const canStart = Boolean(selectedCaseId);

  const startAnalysis = async () => {
    if (!selectedCaseId) return;
    setIsStarting(true);
    setError(null);

    try {
      const session = await apiClient.initUpload({
        case_id: selectedCaseId,
        source: "cohort_select",
      });

      const job = await apiClient.createAnalysisJob({
        session_id: session.session_id,
        case_id: selectedCaseId,
      });

      router.push(`/analysis/${job.job_id}?case_id=${selectedCaseId}`);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Failed to start analysis job. Please retry.",
      );
      setIsStarting(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
      <PageSection className="bg-shell-panel/70">
        <h1 className="text-lg font-semibold text-slate-100">Select a cached LUAD case</h1>
        <p className="mt-1 text-sm text-slate-300">
          Step 1/3 · Upload is temporarily disabled. Choose a preloaded cohort case only.
        </p>

        <div className="mt-4">
          <label htmlFor="case-selector" className="mb-2 block text-xs font-semibold text-slate-300">
            Cohort case selector
          </label>
          <select
            id="case-selector"
            className="w-full rounded-md border border-shell-border bg-slate-900 px-3 py-2 text-sm text-slate-100"
            value={selectedCaseId}
            onChange={(event) => setSelectedCaseId(event.target.value)}
          >
            {cases.map((entry) => (
              <option key={entry.case_id} value={entry.case_id}>
                {entry.case_id} · {entry.display_name}
              </option>
            ))}
          </select>
        </div>

        <div className="mt-4 rounded-lg border border-slate-600/60 bg-slate-900/30 p-3 text-xs text-slate-300">
          <p>
            <span className="font-semibold text-slate-100">Selected:</span> {selectedCase?.case_id} ({selectedCase?.stage ?? "Stage N/A"})
          </p>
          <p className="mt-1">Smoking status: {selectedCase?.smoking_status ?? "Unknown"}</p>
        </div>

        <div className="mt-4 rounded-lg border border-amber-400/30 bg-amber-500/10 p-3 text-xs text-amber-100">
          Upload is disabled for this build. Analysis runs from cached pathology/transcriptomics/clinical data on DGX.
        </div>

        {error ? <p className="mt-3 text-sm text-rose-300">{error}</p> : null}

        <div className="mt-5 flex gap-2">
          <button
            type="button"
            disabled={!canStart || isStarting}
            onClick={startAnalysis}
            className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-900 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isStarting ? "Starting..." : "Start analysis from cached data"}
          </button>
        </div>
      </PageSection>

      <PageSection className="bg-shell-panel/50">
        <h2 className="text-sm font-semibold text-slate-100">Flow preview</h2>
        <ol className="mt-3 space-y-3 text-xs text-slate-300">
          <li>
            <span className="font-semibold text-slate-100">1) Select cached cohort case</span>
            <p>Choose a preloaded cohort case (file upload disabled in this build).</p>
          </li>
          <li>
            <span className="font-semibold text-slate-100">2) Analysis progress</span>
            <p>Track queued/running/completed states by modality.</p>
          </li>
          <li>
            <span className="font-semibold text-slate-100">3) Patient workspace + chat</span>
            <p>Inspect pathology/RNA/clinical/fusion cards and query the agent.</p>
          </li>
        </ol>
      </PageSection>
    </div>
  );
}
