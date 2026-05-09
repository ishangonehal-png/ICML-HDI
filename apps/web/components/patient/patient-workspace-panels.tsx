"use client";

import { useId, useState } from "react";

import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import { ClinicalSummaryPanel } from "@/components/panels/clinical-summary-panel";
import { IOImmunePanel } from "@/components/panels/io-immune-panel";
import { PathologyPanel } from "@/components/panels/pathology-panel";
import { SimilarPatientsPanel } from "@/components/panels/similar-patients-panel";
import { SurvivalPanel } from "@/components/panels/survival-panel";
import { TranscriptomicsPanel } from "@/components/panels/transcriptomics-panel";
import type {
  ClinicalPanelData,
  IOImmunePanelData,
  PathologyPanelData,
  PatientWorkspaceSectionState,
  TranscriptomicsPanelData,
} from "@/lib/patient-workspace";
import { cn } from "@/lib/utils";

interface PatientWorkspacePanelsProps {
  pathologyState: PatientWorkspaceSectionState<PathologyPanelData>;
  transcriptomicsState: PatientWorkspaceSectionState<TranscriptomicsPanelData>;
  clinicalState: PatientWorkspaceSectionState<ClinicalPanelData>;
  ioImmuneState: PatientWorkspaceSectionState<IOImmunePanelData>;
}

type WorkspaceTabKey = "pathology" | "transcriptomics" | "clinical" | "io-response" | "similar-patients";
type MountedTabsState = Record<WorkspaceTabKey, boolean>;

const WORKSPACE_TABS: Array<{
  key: WorkspaceTabKey;
  label: string;
  description: string;
  tooltip: string;
}> = [
  {
    key: "pathology",
    label: "Pathology",
    description: "WSI heatmap, tissue composition, and top evidence tiles",
    tooltip:
      "Pathology tab is the image-first entry point for this case and emphasizes where slide-level model attention concentrates. It combines viewport guidance, tissue fractions, and ranked evidence tiles so you can connect global morphology to local patches. Use it to localize visual signal quickly, then cross-check with RNA and clinical evidence for consistency.",
  },
  {
    key: "transcriptomics",
    label: "Transcriptomics",
    description: "CYT/GEP/TIDE, RNA evidence, and DEG visualizations",
    tooltip:
      "Transcriptomics tab summarizes RNA-derived immune and differential-expression proxies that can materially shift IO Immune behavior. Signature cards provide compact endpoint context, while gene evidence and plots reveal directionality, significance, and expression-dependent stability. Read this tab to test whether molecular trends reinforce or contradict pathology cues before interpreting case-level IO tiering.",
  },
  {
    key: "clinical",
    label: "Clinical summary",
    description: "Structured summary, report highlights, and survival baseline",
    tooltip:
      "Clinical summary tab provides normalized patient context extracted from source reports, including stage, smoking metadata, eligibility heuristics, and survival baseline proxies. It helps anchor narrative interpretation so modality changes are read in context rather than in isolation. Treat these fields as concise orientation aids and verify key claims against provenance-linked source highlights.",
  },
  {
    key: "io-response",
    label: "IO response",
    description: "Hot/Warm/Cold tier, component weights, and RNA-adjusted readiness",
    tooltip:
      "IO response tab isolates the immunotherapy readiness view so physicians can inspect the tier, score components, and RNA effect without mixing it into pathology or clinical context.",
  },
  {
    key: "similar-patients",
    label: "Similar patients",
    description: "Nearest-neighbor cohort retrieval for analogous cases",
    tooltip:
      "Similar patients tab surfaces cohort neighbors based on multimodal similarity, giving physicians quick comparative context without burying it inside another score panel.",
  },
];

function PanelStateCard({
  title,
  detail,
  status,
}: {
  title: string;
  detail: string;
  status: "loading" | "error";
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-4 text-sm",
        status === "loading"
          ? "border-shell-border bg-shell-panel/60 text-slate-200"
          : "border-rose-400/40 bg-rose-900/20 text-rose-100",
      )}
    >
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-xs opacity-90">{detail}</p>
      {status === "loading" ? <div className="mt-3 h-2 w-40 animate-pulse rounded bg-slate-700/60" /> : null}
    </div>
  );
}

export function PatientWorkspacePanels({
  pathologyState,
  transcriptomicsState,
  clinicalState,
  ioImmuneState,
}: PatientWorkspacePanelsProps) {
  const [activeTab, setActiveTab] = useState<WorkspaceTabKey>("pathology");
  const [mountedTabs, setMountedTabs] = useState<MountedTabsState>({
    pathology: true,
    transcriptomics: false,
    clinical: false,
    "io-response": false,
    "similar-patients": false,
  });
  const tabNamespace = useId();

  const activateTab = (tab: WorkspaceTabKey) => {
    setActiveTab(tab);
    setMountedTabs((current) => (current[tab] ? current : { ...current, [tab]: true }));
  };

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-shell-border bg-shell-panel/70 p-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-cyan-200/75">Workspace panels</p>
            <p className="mt-1 text-sm text-slate-300">Choose the evidence surface you want to review first.</p>
          </div>
        </div>

        <div role="tablist" aria-label="Patient modality panels" className="grid gap-2 lg:grid-cols-5">
          {WORKSPACE_TABS.map((tab) => {
            const isActive = tab.key === activeTab;
            const tabId = `${tabNamespace}-${tab.key}-tab`;
            const panelId = `${tabNamespace}-${tab.key}-panel`;

            return (
              <div key={tab.key} className="relative">
                <button
                  id={tabId}
                  role="tab"
                  type="button"
                  aria-selected={isActive}
                  aria-controls={panelId}
                  onClick={() => activateTab(tab.key)}
                  className={cn(
                    "w-full rounded-xl border px-4 py-3 pr-11 text-left transition",
                    isActive
                      ? "border-cyan-300 bg-gradient-to-br from-cyan-500/18 to-blue-500/10 text-cyan-100 shadow-[0_0_0_1px_rgba(34,211,238,0.12)]"
                      : "border-shell-border bg-slate-950/35 text-slate-300 hover:border-cyan-400/50 hover:bg-slate-900/55 hover:text-cyan-100",
                  )}
                >
                  <p className="text-sm font-semibold uppercase tracking-wide">{tab.label}</p>
                  <p className="mt-1 text-[11px] leading-snug opacity-90">{tab.description}</p>
                </button>
                <InfoEyeTooltip
                  ariaLabel={`Patient workspace ${tab.label} tab explanation`}
                  description={tab.tooltip}
                  className="absolute right-2 top-2"
                />
              </div>
            );
          })}
        </div>
      </section>

      {WORKSPACE_TABS.map((tab) => {
        const isActive = tab.key === activeTab;
        const isMounted = mountedTabs[tab.key];
        const tabId = `${tabNamespace}-${tab.key}-tab`;
        const panelId = `${tabNamespace}-${tab.key}-panel`;

        return (
          <section
            key={tab.key}
            id={panelId}
            role="tabpanel"
            aria-labelledby={tabId}
            hidden={!isActive}
            className="space-y-4"
          >
            {isMounted && tab.key === "pathology" ? (
              pathologyState.status === "loading" ? (
                <PanelStateCard
                  status="loading"
                  title="Loading pathology panel..."
                  detail="Fetching WSI heatmap, tissue composition, and evidence tiles."
                />
              ) : pathologyState.status === "error" || !pathologyState.data ? (
                <PanelStateCard
                  status="error"
                  title="Pathology panel unavailable"
                  detail={
                    pathologyState.errorMessage ??
                    "Unable to load pathology endpoints for this case right now."
                  }
                />
              ) : (
                <PathologyPanel
                  tissue={pathologyState.data.tissue}
                  heatmap={pathologyState.data.heatmap}
                  evidence={pathologyState.data.evidence}
                  reportHighlights={clinicalState.data?.summary?.report_highlights ?? []}
                />
              )
            ) : null}

            {isMounted && tab.key === "transcriptomics" ? (
              transcriptomicsState.status === "loading" ? (
                <PanelStateCard
                  status="loading"
                  title="Loading transcriptomics panel..."
                  detail="Fetching CYT/GEP/TIDE signatures, RNA evidence, and DEG artifacts."
                />
              ) : transcriptomicsState.status === "error" || !transcriptomicsState.data ? (
                <PanelStateCard
                  status="error"
                  title="Transcriptomics panel unavailable"
                  detail={
                    transcriptomicsState.errorMessage ??
                    "Unable to load transcriptomics endpoints for this case right now."
                  }
                />
              ) : (
                <TranscriptomicsPanel
                  cyt={transcriptomicsState.data.cyt}
                  gep={transcriptomicsState.data.gep}
                  tide={transcriptomicsState.data.tide}
                  evidence={transcriptomicsState.data.evidence}
                  degVolcano={transcriptomicsState.data.degVolcano}
                  plots={transcriptomicsState.data.plots}
                />
              )
            ) : null}

            {isMounted && tab.key === "clinical" ? (
              clinicalState.status === "loading" ? (
                <PanelStateCard
                  status="loading"
                  title="Loading clinical summary panel..."
                  detail="Fetching patient summary, eligibility heuristics, and survival baseline."
                />
              ) : clinicalState.status === "error" || !clinicalState.data ? (
                <PanelStateCard
                  status="error"
                  title="Clinical summary panel unavailable"
                  detail={
                    clinicalState.errorMessage ??
                    "Unable to load clinical endpoints for this case right now."
                  }
                />
              ) : (
                <>
                  <ClinicalSummaryPanel
                    summary={clinicalState.data.summary}
                    eligibility={clinicalState.data.eligibility}
                    survival={clinicalState.data.survival}
                  />
                  <SurvivalPanel survivalMlp={clinicalState.data.survivalMlp} />
                </>
              )
            ) : null}

            {isMounted && tab.key === "io-response" ? (
              ioImmuneState.status === "loading" ? (
                <PanelStateCard
                  status="loading"
                  title="Loading IO response panel..."
                  detail="Fetching provisional and refined IO readiness components."
                />
              ) : ioImmuneState.status === "error" || !ioImmuneState.data ? (
                <PanelStateCard
                  status="error"
                  title="IO response panel unavailable"
                  detail={ioImmuneState.errorMessage ?? "Unable to load IO response for this case right now."}
                />
              ) : (
                <IOImmunePanel ioScore={ioImmuneState.data.score} />
              )
            ) : null}

            {isMounted && tab.key === "similar-patients" ? (
              ioImmuneState.status === "loading" ? (
                <PanelStateCard
                  status="loading"
                  title="Loading similar patients panel..."
                  detail="Fetching nearest-neighbor cohort matches for this case."
                />
              ) : ioImmuneState.status === "error" || !ioImmuneState.data ? (
                <PanelStateCard
                  status="error"
                  title="Similar patients panel unavailable"
                  detail={ioImmuneState.errorMessage ?? "Unable to load similar patients for this case right now."}
                />
              ) : (
                <SimilarPatientsPanel
                  similarCases={ioImmuneState.data.similarCases}
                  errorMessage={ioImmuneState.data.similarCasesError}
                />
              )
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
