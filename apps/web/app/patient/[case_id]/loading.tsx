export default function PatientWorkspaceLoading() {
  return (
    <div className="relative left-1/2 w-screen max-w-none -translate-x-1/2 px-4 lg:px-6">
      <div className="grid gap-4 xl:grid-cols-[clamp(220px,18vw,300px)_minmax(0,1fr)_clamp(280px,24vw,420px)] xl:items-start">
        <div className="rounded-xl border border-shell-border bg-shell-panel/70 p-3 xl:sticky xl:top-6 xl:h-[calc(100dvh-3rem)]">
          <div className="h-4 w-24 animate-pulse rounded bg-slate-700/60" />
          <div className="mt-3 space-y-2">
            {Array.from({ length: 8 }).map((_, idx) => (
              <div
                // eslint-disable-next-line react/no-array-index-key
                key={idx}
                className="h-14 animate-pulse rounded-lg border border-shell-border bg-slate-900/40"
              />
            ))}
          </div>
        </div>

        <div className="min-w-0 space-y-4">
          <div className="rounded-xl border border-shell-border bg-shell-panel/70 p-4 text-sm text-slate-200">
            Loading patient workspace...
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="h-56 animate-pulse rounded-xl border border-shell-border bg-slate-900/40" />
            <div className="h-56 animate-pulse rounded-xl border border-shell-border bg-slate-900/40" />
          </div>
        </div>

        <div className="min-w-0 xl:sticky xl:top-6 xl:h-[calc(100dvh-3rem)]">
          <div className="h-[420px] animate-pulse rounded-xl border border-shell-border bg-shell-panel/60 xl:h-full" />
        </div>
      </div>
    </div>
  );
}
