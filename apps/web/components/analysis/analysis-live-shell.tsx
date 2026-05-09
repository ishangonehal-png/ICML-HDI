"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AnalysisStatusTimelineCard } from "@/components/analysis/analysis-status-timeline-card";
import { ModalityStatusGrid } from "@/components/analysis/modality-status-grid";
import { PageSection } from "@/components/common/page-section";
import { apiClient, type AnalysisJobResponse } from "@/lib/api-client";

interface AnalysisLiveShellProps {
  initialJob: AnalysisJobResponse;
}

function toErrorMessage(value: unknown): string {
  if (value instanceof Error && value.message.trim().length > 0) {
    return value.message;
  }
  return "Unable to refresh analysis status. Retry shortly.";
}

export function AnalysisLiveShell({ initialJob }: AnalysisLiveShellProps) {
  const [job, setJob] = useState(initialJob);
  const [pollError, setPollError] = useState<string | null>(null);

  useEffect(() => {
    setJob(initialJob);
  }, [initialJob]);

  useEffect(() => {
    if (job.state === "completed" || job.state === "failed") {
      return;
    }

    let isCancelled = false;

    const poll = async () => {
      try {
        const refreshed = await apiClient.getAnalysisJob(job.job_id, job.case_id);
        if (isCancelled) {
          return;
        }
        setJob(refreshed);
        setPollError(null);
      } catch (error) {
        if (isCancelled) {
          return;
        }
        setPollError(toErrorMessage(error));
      }
    };

    const timerId = window.setInterval(() => {
      void poll();
    }, 3000);
    void poll();

    return () => {
      isCancelled = true;
      window.clearInterval(timerId);
    };
  }, [job.job_id, job.case_id, job.state]);

  const modalitySteps = useMemo(
    () => job.steps.filter((step) => step.key !== "queue"),
    [job.steps],
  );

  return (
    <div className="space-y-4">
      <AnalysisStatusTimelineCard
        jobId={job.job_id}
        state={job.state}
        steps={job.steps}
        events={job.events}
      />

      {pollError ? (
        <PageSection className="border-amber-300/60 bg-amber-500/10 text-amber-100">
          <p className="text-xs">{pollError}</p>
        </PageSection>
      ) : null}

      <ModalityStatusGrid steps={modalitySteps} />

      {job.errors?.length ? (
        <PageSection className="border-rose-400/60 bg-rose-500/15 text-rose-100">
          <p className="font-semibold">Error surfaced</p>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs">
            {job.errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
          <Link
            href={`/upload?case_id=${encodeURIComponent(job.case_id)}`}
            className="mt-3 inline-block rounded-md border border-rose-300/60 px-3 py-1 text-xs text-rose-100"
          >
            Retry from upload
          </Link>
        </PageSection>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Link href="/upload" className="rounded-md border border-shell-border px-3 py-2 text-sm text-slate-200">
          Back to upload
        </Link>

        {job.state === "completed" ? (
          <Link
            href={`/patient/${job.case_id}`}
            className="rounded-md bg-emerald-500 px-3 py-2 text-sm font-semibold text-slate-900 hover:bg-emerald-400"
          >
            Open patient workspace
          </Link>
        ) : job.state === "failed" ? (
          <Link
            href={`/upload?case_id=${encodeURIComponent(job.case_id)}`}
            className="rounded-md border border-rose-300/50 px-3 py-2 text-sm text-rose-100"
          >
            Retry analysis
          </Link>
        ) : (
          <a
            href={`/analysis/${job.job_id}?case_id=${encodeURIComponent(job.case_id)}`}
            className="rounded-md border border-cyan-300/50 px-3 py-2 text-sm text-cyan-100"
          >
            Open standalone refresh
          </a>
        )}
      </div>
    </div>
  );
}
