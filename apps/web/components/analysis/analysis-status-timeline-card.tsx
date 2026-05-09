import type { AnalysisJobEvent, AnalysisStepStatus, JobState } from "@/lib/api-client";

import { timelineStatusClass } from "@/components/analysis/status-styles";
import { PageSection } from "@/components/common/page-section";

interface AnalysisStatusTimelineCardProps {
  jobId: string;
  state: JobState;
  steps: AnalysisStepStatus[];
  events?: AnalysisJobEvent[];
}

function formatEventTime(timestamp: string | undefined): string {
  if (!timestamp) {
    return "time unavailable";
  }
  const parsed = Date.parse(timestamp);
  if (Number.isNaN(parsed)) {
    return "time unavailable";
  }
  return new Date(parsed).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function AnalysisStatusTimelineCard({ jobId, state, steps, events }: AnalysisStatusTimelineCardProps) {
  const recentEvents = (events ?? []).slice(-6).reverse();

  return (
    <PageSection className="bg-shell-panel/70">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Analysis job {jobId}</h1>
          <p className="text-sm text-slate-300">Step 2/3 · Track asynchronous modality progress.</p>
        </div>

        <span className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase ${timelineStatusClass[state]}`}>
          {state}
        </span>
      </div>

      <ol className="mt-5 space-y-3">
        {steps.map((step, index) => (
          <li key={step.key} className="relative rounded-lg border border-shell-border bg-slate-900/35 p-3 pl-4">
            {index !== steps.length - 1 ? (
              <span className="absolute -bottom-3 left-6 h-3 w-px bg-shell-border" aria-hidden />
            ) : null}
            <div className="flex items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium text-slate-100">{step.label}</p>
                {step.detail ? <p className="text-xs text-slate-300">{step.detail}</p> : null}
              </div>
              <span
                className={`rounded-full border px-2 py-1 text-[11px] font-medium uppercase ${timelineStatusClass[step.status]}`}
              >
                {step.status}
              </span>
            </div>
          </li>
        ))}
      </ol>

      {recentEvents.length > 0 ? (
        <div className="mt-5 rounded-lg border border-shell-border bg-slate-900/30 p-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-200">Backend events</h2>
          <ul className="mt-2 space-y-2 text-xs text-slate-300">
            {recentEvents.map((event, index) => (
              <li key={`${event.event_type}-${event.created_at ?? "unknown"}-${index}`}>
                <p className="text-slate-100">{event.message}</p>
                <p className="text-[11px] uppercase tracking-wide text-slate-400">
                  {event.event_type} · {formatEventTime(event.created_at)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </PageSection>
  );
}
