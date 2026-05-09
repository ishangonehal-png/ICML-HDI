import { ContentCard } from "@/components/common/content-card";
import { InfoEyeTooltip } from "@/components/common/info-eye-tooltip";
import { MissingModalityState } from "@/components/common/missing-modality-state";
import { PanelShell } from "@/components/common/panel-shell";
import { TranscriptomicsExpressionHeatmap } from "@/components/panels/transcriptomics-expression-heatmap";
import { TranscriptomicsMaPlot } from "@/components/panels/transcriptomics-ma-plot";
import { TranscriptomicsRawExpressionMatrix } from "@/components/panels/transcriptomics-raw-expression-matrix";
import { TranscriptomicsVolcanoPlot } from "@/components/panels/transcriptomics-volcano-plot";
import type {
  CytResponse,
  GepResponse,
  TideResponse,
  TranscriptomicsDegVolcanoResponse,
  TranscriptomicsEvidenceResponse,
  TranscriptomicsPlotsResponse,
  TranscriptomicsRawExpressionMatrixPreview,
} from "@/lib/api-client";

interface TranscriptomicsPanelProps {
  cyt: CytResponse;
  gep: GepResponse;
  tide: TideResponse;
  evidence: TranscriptomicsEvidenceResponse;
  degVolcano: TranscriptomicsDegVolcanoResponse;
  plots?: TranscriptomicsPlotsResponse | null;
}

const TOOLTIP_COPY = {
  panelTitle:
    "Transcriptomics panel organizes RNA-derived endpoints into one interpretation surface for this case. It combines compact signature scores, gene-level evidence, and differential-expression visuals so reviewers can assess whether molecular patterns support or challenge pathology and clinical impressions. Treat this as a multimodal evidence bridge, not a standalone biomarker verdict.",
  panelSubtitle:
    "The subtitle summarizes the RNA workflow shown below: score cards for CYT/GEP/TIDE, an interactive DEG volcano, a bounded raw matrix preview, then RNA evidence summaries. Reading these together helps distinguish broad immune-pattern shifts from single-gene noise and clarifies why transcriptomics may increase or dampen fusion output relative to provisional baseline.",
  panelMeta:
    "RNA metadata identifies the transcriptomics processing method, release version, and run timestamp behind all values in this panel. Check it before comparing cases or historical snapshots because normalization changes or signature updates can alter magnitudes and ranking. Provenance-aware comparison prevents misattributing pipeline revisions to biological differences.",
  panelProxyEstimate:
    "Proxy estimate labeling communicates that transcriptomic endpoints here are research-oriented abstractions derived from curated signatures and model logic. They support relative pattern analysis within this cohort but are not validated diagnostic assays. Use them alongside modality completeness, uncertainty context, and external evidence rather than elevating any single RNA metric to clinical truth.",
  cyt: "CYT is a cytolytic activity proxy derived from normalized GZMA and PRF1 expression. Higher values often indicate stronger immune killing potential in the tumor microenvironment, but this remains a research proxy rather than direct evidence of response. Interpret CYT together with GEP, TIDE, RNA coverage, and pathology context before deciding biological significance.",
  gep: "GEP summarizes an inflamed tumor microenvironment signal using an 18-gene expression signature. Elevated values can reflect interferon signaling and T-cell infiltration patterns that may align with immune-active biology. Because this score is signature-based and cohort-sensitive, use it as comparative evidence across cases, not as a stand-alone treatment decision metric.",
  tide: "TIDE is a transcriptomic proxy that estimates immune dysfunction and exclusion patterns using expression signatures. Lower values can suggest reduced escape pressure, while higher values may indicate potential resistance mechanisms, but this endpoint is still experimental in our workflow. Always compare TIDE with CYT, GEP, and case-level quality metadata before interpretation.",
  rnaEvidence:
    "Top genes list the strongest RNA contributors surfaced for this case after preprocessing. The normalized count column is scaled expression intensity in the analysis space, so it is useful for relative ranking within this pipeline but not a direct raw-read count. Use gene-level values as directional support for interpretation notes and pathway-level hypotheses.",
  interpretationNotes:
    "Interpretation notes are generated summaries that connect transcriptomic signals to potential biological themes. They are meant to accelerate review, not replace expert judgment. Treat each note as a hypothesis anchored to available evidence, and verify against gene-level values, modality coverage, and known limitations before using the statement in downstream discussion.",
  degVolcano:
    "The DEG volcano proxy plots effect size on the x-axis and significance proxy on the y-axis for observed genes. Dashed vertical lines mark absolute log2 fold-change threshold, and the horizontal line marks the significance cutoff. Points outside these guides are highlighted as stronger candidates. This is a ranked exploration view, not a clinical differential-expression report.",
  maPlot:
    "MA plot emphasizes expression-dependent behavior by pairing average abundance with fold-change for each gene. It helps separate robust shifts from low-expression volatility and highlights significant outliers for follow-up. Use it to sanity-check volcano patterns and determine whether candidate genes remain informative across expression ranges rather than only at sparse counts.",
  rawMatrixPreview:
    "Raw matrix preview is a bounded window into gene-level expression values from the underlying RNA matrix. It preserves raw-scale context while exposing quick filtering and row inspection so reviewers can verify candidate genes behind normalized summaries. Because this is intentionally truncated for responsiveness, use it as an interactive preview rather than a full export.",
  expressionHeatmap:
    "Expression heatmap provides a compact matrix view of normalized gene activity across selected rows and symbols. It is useful for spotting coordinated up/down patterns, outlier rows, and relative dynamic range within this case. Because color scaling is local to displayed values, interpret intensity comparatively here and avoid cross-case conclusions without matched normalization context.",
  missingModalityNotice:
    "This panel stays visible even when RNA is missing so reviewers can see why transcriptomics did not contribute to the active run. In this state, fusion output remains provisional from non-RNA modalities only, and transcriptomic refinements are intentionally withheld until ingestion, coverage, and QC checks succeed in a later pass.",
  scoreUnavailable:
    "'Not available' means this endpoint could not be computed for the current case, often due to missing RNA input, insufficient coverage, or quality-control gating. The card stays visible to preserve transparent modality accounting. Treat N/A as genuinely missing evidence for this run, not as a low biological signal or negative result.",
  degUnavailableState:
    "DEG visuals can be unavailable when differential-expression inputs fail ingestion, coverage, or quality thresholds in the transcriptomics pipeline. Other cards may still provide useful RNA context, but gene-level shift diagnostics are incomplete for this run. Treat this as missing explainability depth rather than contradictory evidence from the available endpoints.",
} as const;

function scoreLabel(value: number | null) {
  return value === null ? "N/A" : value.toFixed(2);
}

const EMPTY_RAW_MATRIX_PREVIEW: TranscriptomicsRawExpressionMatrixPreview = {
  available: false,
  data_source: "unavailable",
  unavailable_reason: "Raw expression matrix preview unavailable for this case.",
  total_genes_observed: 0,
  returned_rows: 0,
  preview_limit: 0,
  truncated: false,
  rows: [],
};

export function TranscriptomicsPanel({
  cyt,
  gep,
  tide,
  evidence,
  degVolcano,
  plots,
}: TranscriptomicsPanelProps) {
  const volcanoSource = plots?.available && plots.volcano ? plots.volcano : degVolcano;
  const rawMatrixPreview = plots?.raw_matrix_preview ?? EMPTY_RAW_MATRIX_PREVIEW;
  const hasRnaDerivedData =
    cyt.available ||
    gep.available ||
    tide.available ||
    evidence.top_genes.length > 0 ||
    volcanoSource.available ||
    rawMatrixPreview.available ||
    (plots?.ma_plot.length ?? 0) > 0 ||
    (plots?.top_genes_bar.length ?? 0) > 0 ||
    Boolean(plots?.expression_heatmap.available);
  const showMissingModalityFallback =
    !hasRnaDerivedData && volcanoSource.availability_code === "missing_input";
  const scoreCards = [
    {
      label: "CYT",
      value: cyt.value,
      available: cyt.available,
      hint: "GZMA + PRF1 cytolytic proxy",
      tooltip: TOOLTIP_COPY.cyt,
    },
    {
      label: "GEP",
      value: gep.value,
      available: gep.available,
      hint: "18-gene inflamed signature",
      tooltip: TOOLTIP_COPY.gep,
    },
    {
      label: "TIDE",
      value: tide.value,
      available: tide.available,
      hint: tide.experimental ? "Experimental gate" : "",
      tooltip: TOOLTIP_COPY.tide,
    },
  ] as const;
  return (
    <PanelShell
      title="Transcriptomics panel"
      subtitle="CYT, GEP, TIDE cards, interactive DEG volcano proxy, raw matrix preview, and RNA evidence"
      meta={cyt.meta}
      tooltips={{
        title: TOOLTIP_COPY.panelTitle,
        subtitle: TOOLTIP_COPY.panelSubtitle,
        meta: TOOLTIP_COPY.panelMeta,
        proxyEstimate: TOOLTIP_COPY.panelProxyEstimate,
      }}
    >
      {showMissingModalityFallback ? (
        <div className="space-y-2">
          <MissingModalityState
            modality="Transcriptomics"
            description="RNA modality missing. Refined score is unavailable and fusion falls back to provisional estimate."
          />
          <div className="flex items-center gap-1 text-[11px] text-slate-400">
            <span>Why this fallback appears</span>
            <InfoEyeTooltip
              ariaLabel="Transcriptomics missing modality fallback explanation"
              content={TOOLTIP_COPY.missingModalityNotice}
            />
          </div>
        </div>
      ) : null}

      <div className="grid gap-2 md:grid-cols-3">
        {scoreCards.map((item) => (
          <ContentCard key={item.label}>
            <div className="flex items-center gap-1">
              <p className="text-xs text-slate-400">{item.label}</p>
              <InfoEyeTooltip ariaLabel={`Transcriptomics ${item.label} score explanation`} content={item.tooltip} />
            </div>
            <p className="mt-1 text-xl font-semibold text-slate-100">{scoreLabel(item.value)}</p>
            <p className="mt-1 text-xs text-slate-300">{item.hint}</p>
            {!item.available ? (
              <div className="mt-1 flex items-center gap-1 text-xs text-amber-200">
                <span>Not available for this case</span>
                <InfoEyeTooltip
                  ariaLabel={`Transcriptomics ${item.label} unavailable explanation`}
                  content={TOOLTIP_COPY.scoreUnavailable}
                  className="text-amber-100"
                />
              </div>
            ) : null}
          </ContentCard>
        ))}
      </div>

      <ContentCard className="mt-3">
        <div className="flex items-center gap-1">
          <p className="text-xs font-semibold text-slate-300">DEG volcano proxy</p>
          <InfoEyeTooltip ariaLabel="Transcriptomics DEG volcano proxy explanation" content={TOOLTIP_COPY.degVolcano} />
        </div>
        {!volcanoSource.available ? (
          <div className="mt-2 flex items-start gap-1 text-xs text-amber-200">
            <p>{volcanoSource.unavailable_reason ?? "DEG volcano proxy unavailable for this case."}</p>
            <InfoEyeTooltip
              ariaLabel="Transcriptomics DEG unavailable explanation"
              content={TOOLTIP_COPY.degUnavailableState}
              className="mt-[-2px]"
            />
          </div>
        ) : (
          <div className="mt-2">
            <TranscriptomicsVolcanoPlot points={volcanoSource.points} plot={volcanoSource.plot} />
          </div>
        )}
      </ContentCard>

      <ContentCard className="mt-3">
        <div className="flex items-center gap-1">
          <p className="text-xs font-semibold text-slate-300">Raw gene expression matrix (preview)</p>
          <InfoEyeTooltip
            ariaLabel="Transcriptomics raw matrix preview explanation"
            content={TOOLTIP_COPY.rawMatrixPreview}
          />
        </div>
        <div className="mt-2">
          <TranscriptomicsRawExpressionMatrix preview={rawMatrixPreview} />
        </div>
      </ContentCard>

      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_1fr]">
        <ContentCard>
          <div className="flex items-center gap-1">
            <p className="text-xs font-semibold text-slate-300">RNA evidence (top genes)</p>
            <InfoEyeTooltip ariaLabel="Transcriptomics RNA evidence explanation" content={TOOLTIP_COPY.rnaEvidence} />
          </div>
          {evidence.top_genes.length === 0 ? (
            <p className="mt-2 text-xs text-slate-400">No transcriptomic evidence generated.</p>
          ) : (
            <ul className="mt-2 space-y-1 text-xs text-slate-200">
              {evidence.top_genes.map((gene) => (
                <li key={gene.symbol} className="flex items-center justify-between">
                  <span>{gene.symbol}</span>
                  <span>{gene.normalized_count.toFixed(1)}</span>
                </li>
              ))}
            </ul>
          )}
        </ContentCard>

        <ContentCard>
          <div className="flex items-center gap-1">
            <p className="text-xs font-semibold text-slate-300">Interpretation notes</p>
            <InfoEyeTooltip ariaLabel="Transcriptomics interpretation notes explanation" content={TOOLTIP_COPY.interpretationNotes} />
          </div>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-300">
            {evidence.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </ContentCard>
      </div>

      {plots?.available && plots.ma_plot.length > 0 ? (
        <ContentCard className="mt-3">
          <div className="flex items-center gap-1">
            <p className="text-xs font-semibold text-slate-300">MA plot</p>
            <InfoEyeTooltip ariaLabel="Transcriptomics MA plot interpretation explanation" content={TOOLTIP_COPY.maPlot} />
          </div>
          <div className="mt-2">
            <TranscriptomicsMaPlot ma_plot={plots.ma_plot} />
          </div>
        </ContentCard>
      ) : null}

      {plots?.available && plots.expression_heatmap.available ? (
        <ContentCard className="mt-3">
          <div className="flex items-center gap-1">
            <p className="text-xs font-semibold text-slate-300">Expression heatmap</p>
            <InfoEyeTooltip
              ariaLabel="Transcriptomics expression heatmap interpretation explanation"
              content={TOOLTIP_COPY.expressionHeatmap}
            />
          </div>
          <div className="mt-2">
            <TranscriptomicsExpressionHeatmap expression_heatmap={plots.expression_heatmap} />
          </div>
        </ContentCard>
      ) : null}
    </PanelShell>
  );
}
