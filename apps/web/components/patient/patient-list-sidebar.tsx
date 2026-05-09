"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { CohortCaseSummary } from "@/lib/api-client";
import { PageSection } from "@/components/common/page-section";

interface PatientListSidebarProps {
  cases: CohortCaseSummary[];
  selectedCaseId: string;
}

export function PatientListSidebar({ cases, selectedCaseId }: PatientListSidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredCases = useMemo(() => {
    if (!normalizedQuery) {
      return cases;
    }

    return cases.filter((entry) => {
      const caseId = entry.case_id.toLowerCase();
      const stage = (entry.stage ?? "").toLowerCase();
      const smoking = (entry.smoking_status ?? "").toLowerCase();
      return (
        caseId.includes(normalizedQuery) ||
        stage.includes(normalizedQuery) ||
        smoking.includes(normalizedQuery)
      );
    });
  }, [cases, normalizedQuery]);

  return (
    <PageSection className="relative z-20 flex min-h-0 flex-col p-3 pointer-events-auto xl:sticky xl:top-6 xl:h-[calc(100dvh-3rem)]">
      <h2 className="text-sm font-semibold text-slate-100">Patient list</h2>
      <p className="mt-1 text-xs text-slate-300">Search by case ID, stage, or smoking status.</p>

      <div className="mt-3">
        <input
          type="search"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search cases..."
          aria-label="Search cases"
          className="w-full rounded-md border border-shell-border bg-slate-950/60 px-2.5 py-1.5 text-xs text-slate-100 placeholder:text-slate-400 focus-visible:border-cyan-300/70 focus-visible:outline-none"
        />
      </div>

      <ul className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {filteredCases.map((entry) => {
          const active = entry.case_id === selectedCaseId;
          const cardClass = `block w-full rounded-lg border px-3 py-2 text-left text-xs transition ${
            active
              ? "border-cyan-300/60 bg-cyan-500/20 text-cyan-50"
              : "border-shell-border bg-slate-900/35 text-slate-200 hover:border-cyan-300/60"
          }`;

          const cardContent = (
            <>
              <p className="font-semibold">{entry.case_id}</p>
              <p>{entry.stage ?? "Stage N/A"}</p>
              <p>{entry.has_transcriptomics ? "RNA available" : "RNA missing"}</p>
            </>
          );

          return (
            <li key={entry.case_id}>
              {active ? (
                <div className={cardClass} aria-current="page">
                  {cardContent}
                </div>
              ) : (
                <Link href={`/patient/${entry.case_id}`} className={cardClass}>
                  {cardContent}
                </Link>
              )}
            </li>
          );
        })}

        {filteredCases.length === 0 ? (
          <li className="rounded-lg border border-shell-border bg-slate-900/30 px-3 py-2 text-xs text-slate-300">
            {normalizedQuery ? `No cases matched "${searchQuery.trim()}".` : "No cases available yet."}
          </li>
        ) : null}
      </ul>

      <Link href="/upload" className="mt-3 inline-block text-xs text-cyan-200">
        ← Back to upload
      </Link>
    </PageSection>
  );
}
