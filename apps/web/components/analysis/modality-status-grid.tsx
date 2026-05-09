import type { AnalysisStepStatus } from "@/lib/api-client";

import { modalityStatusClass } from "@/components/analysis/status-styles";
import { PageSection } from "@/components/common/page-section";

interface ModalityStatusGridProps {
  steps: AnalysisStepStatus[];
}

export function ModalityStatusGrid({ steps }: ModalityStatusGridProps) {
  return (
    <PageSection>
      <h2 className="text-sm font-semibold text-slate-100">Per-modality status</h2>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {steps.map((step) => (
          <div key={step.key} className={`rounded-lg border px-3 py-2 text-sm ${modalityStatusClass[step.status]}`}>
            <p className="font-medium capitalize">{step.label}</p>
            <p className="mt-1 text-xs text-slate-300">{step.detail ?? "No additional details."}</p>
          </div>
        ))}
      </div>
    </PageSection>
  );
}
