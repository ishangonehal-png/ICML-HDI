import type { JobState } from "@/lib/api-client";

export const timelineStatusClass: Record<JobState, string> = {
  queued: "border-slate-500 bg-slate-700/40 text-slate-200",
  running: "border-cyan-400 bg-cyan-500/20 text-cyan-100",
  completed: "border-emerald-400 bg-emerald-500/20 text-emerald-100",
  failed: "border-rose-400 bg-rose-500/20 text-rose-100",
};

export const modalityStatusClass: Record<JobState, string> = {
  queued: "border-slate-500/70 bg-slate-900/40 text-slate-200",
  running: "border-cyan-400/60 bg-cyan-500/15 text-cyan-100",
  completed: "border-emerald-400/60 bg-emerald-500/15 text-emerald-100",
  failed: "border-rose-400/60 bg-rose-500/15 text-rose-100",
};
