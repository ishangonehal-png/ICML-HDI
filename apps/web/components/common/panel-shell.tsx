import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import { cn } from "@/lib/utils";

interface PanelMeta {
  method: string;
  version: string;
  timestamp: string;
}

interface PanelShellTooltipCopy {
  title?: string;
  subtitle?: string;
  meta?: string;
  proxyEstimate?: string;
}

interface PanelShellProps {
  title: string;
  subtitle?: string;
  meta?: PanelMeta;
  className?: string;
  tooltips?: PanelShellTooltipCopy;
  children: React.ReactNode;
}

const DEFAULT_META_TOOLTIP =
  "Method and version identify which pipeline configuration produced this card, while timestamp anchors when that output was generated. Together they make panel-level provenance auditable across reruns, branches, and demos. Compare metadata whenever values differ to determine whether score changes come from new evidence, model updates, or preprocessing revisions.";

const DEFAULT_PROXY_ESTIMATE_TOOLTIP =
  "Proxy estimate indicates this panel reports research-grade model outputs rather than clinically validated predictions. It signals that values are intended for exploratory comparison, hypothesis generation, and debugging across cases. Always pair proxy endpoints with uncertainty context, modality availability, and source provenance before using them in any high-stakes interpretation.";

function formatMetaTimestamp(timestamp: string): string {
  const normalized = timestamp.trim();
  const isoUtcPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;

  if (isoUtcPattern.test(normalized)) {
    return normalized.replace("T", " ").replace(/\.\d+Z$/, " UTC").replace("Z", " UTC");
  }

  return normalized;
}

export function PanelShell({
  title,
  subtitle,
  meta,
  className,
  tooltips,
  children,
}: PanelShellProps) {
  return (
    <section className={cn("rounded-xl border border-shell-border bg-shell-panel/70 p-4", className)}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5">
            <h2 className="text-base font-semibold text-slate-100">{title}</h2>
            {tooltips?.title ? (
              <InfoEyeTooltip
                ariaLabel={`${title} title explanation`}
                description={tooltips.title}
                className="shrink-0"
              />
            ) : null}
          </div>
          {subtitle ? (
            <div className="mt-1 flex items-start gap-1.5">
              <p className="text-xs text-slate-300">{subtitle}</p>
              {tooltips?.subtitle ? (
                <InfoEyeTooltip
                  ariaLabel={`${title} subtitle explanation`}
                  description={tooltips.subtitle}
                  className="mt-0.5 shrink-0"
                />
              ) : null}
            </div>
          ) : null}
        </div>

        {meta ? (
          <div className="rounded-lg border border-cyan-400/30 bg-cyan-900/20 px-2 py-1 text-[11px] text-cyan-100">
            <div className="flex items-center gap-1 font-medium">
              <p>Proxy estimate</p>
              <InfoEyeTooltip
                ariaLabel={`${title} proxy estimate explanation`}
                description={tooltips?.proxyEstimate ?? DEFAULT_PROXY_ESTIMATE_TOOLTIP}
                align="end"
                className="shrink-0"
              />
            </div>
            <div className="mt-0.5 flex items-center gap-1">
              <span>
                {meta.method} · {meta.version}
              </span>
              <InfoEyeTooltip
                ariaLabel={`${title} method/version metadata explanation`}
                description={tooltips?.meta ?? DEFAULT_META_TOOLTIP}
                align="end"
                className="shrink-0"
              />
            </div>
            <div>{formatMetaTimestamp(meta.timestamp)}</div>
          </div>
        ) : null}
      </div>
      {children}
    </section>
  );
}
