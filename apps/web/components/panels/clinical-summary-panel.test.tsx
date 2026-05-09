import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import { ClinicalSummaryPanel } from "./clinical-summary-panel";

const meta = {
  method: "clinical-extract-v1",
  version: "2026.03",
  timestamp: "2026-03-08T00:00:00Z",
  proxy_estimate: true as const,
};

const summary = {
  case_id: "TCGA-05-4244",
  stage: "IIIA",
  smoking_status: "Former smoker",
  age_at_diagnosis: 61,
  diagnosis: "LUAD",
  report_highlights: ["Primary tumor in right upper lobe."],
  meta,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ClinicalSummaryPanel", () => {
  it("keeps clinical endpoint labels mapped to info-eye triggers", () => {
    vi.spyOn(apiClient, "getClinicalTrialMatches").mockResolvedValue({
      case_id: "TCGA-05-4244",
      available: true,
      trials: [],
      data_source: "modality_result",
      unavailable_reason: null,
      query_terms: ["lung cancer"],
      meta,
    });
    render(
      <ClinicalSummaryPanel
        summary={summary}
        eligibility={{
          case_id: "TCGA-05-4244",
          eligible_trials: 2,
          rationale: ["PD-L1 pattern aligned with exploratory cohort filter."],
          meta,
        }}
        survival={{
          case_id: "TCGA-05-4244",
          risk_group: "intermediate",
          baseline_months: 24,
          confidence_interval: [18, 30],
          meta,
        }}
      />, 
    );

    expect(screen.getByRole("button", { name: "Clinical summary Stage explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clinical summary Smoking status explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clinical summary Matched trials (live) explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clinical summary trial count semantics" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clinical summary survival baseline explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clinical summary Risk group explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clinical summary Baseline months explanation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clinical summary Confidence interval (mo) explanation" })).toBeInTheDocument();
  });

  it("shows live matched-trial count from ClinicalTrials.gov on preload", async () => {
    vi.spyOn(apiClient, "getClinicalTrialMatches").mockResolvedValue({
      case_id: "TCGA-05-4244",
      available: true,
      trials: [
        {
          title: "Trial A",
          nct_id: "NCT10000001",
          status: "RECRUITING",
          phase: "Phase 2",
          match_score: 7,
          match_reasons: ["Reason A"],
          rationale: "Reason A",
          study_url: "https://clinicaltrials.gov/study/NCT10000001",
        },
        {
          title: "Trial B",
          nct_id: "NCT10000002",
          status: "RECRUITING",
          phase: "Phase 2",
          match_score: 6,
          match_reasons: ["Reason B"],
          rationale: "Reason B",
          study_url: "https://clinicaltrials.gov/study/NCT10000002",
        },
        {
          title: "Trial C",
          nct_id: "NCT10000003",
          status: "RECRUITING",
          phase: "Phase 3",
          match_score: 5,
          match_reasons: ["Reason C"],
          rationale: "Reason C",
          study_url: "https://clinicaltrials.gov/study/NCT10000003",
        },
      ],
      data_source: "modality_result",
      unavailable_reason: null,
      query_terms: ["lung cancer", "stage iii", "former smoker"],
      meta,
    });

    render(<ClinicalSummaryPanel summary={summary} eligibility={null} survival={null} />);

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("3 matched trials")).toBeInTheDocument();
    expect(screen.getByText("Live count from ClinicalTrials.gov.")).toBeInTheDocument();
  });

  it("shows unavailable state when live trial query is unavailable", async () => {
    vi.spyOn(apiClient, "getClinicalTrialMatches").mockResolvedValue({
      case_id: "TCGA-05-4244",
      available: false,
      trials: [],
      data_source: "modality_result",
      unavailable_reason: "ClinicalTrials.gov unavailable: Timeout",
      query_terms: ["lung cancer"],
      meta,
    });

    render(<ClinicalSummaryPanel summary={summary} eligibility={null} survival={null} />);

    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("ClinicalTrials.gov unavailable: Timeout")).toBeInTheDocument();
  });

  it("opens matched trials drawer and renders trial rows", async () => {
    vi.spyOn(apiClient, "getClinicalTrialMatches").mockResolvedValue({
      case_id: "TCGA-05-4244",
      available: true,
      trials: [
        {
          title: "Stage III lung adenocarcinoma immunotherapy",
          nct_id: "NCT12345678",
          status: "RECRUITING",
          phase: "Phase 2",
          match_score: 9,
          match_reasons: ["Condition aligned with lung cancer focus."],
          rationale: "Condition aligned with lung cancer focus.",
          study_url: "https://clinicaltrials.gov/study/NCT12345678",
        },
      ],
      data_source: "modality_result",
      unavailable_reason: null,
      query_terms: ["lung cancer", "stage iii", "former smoker"],
      meta,
    });

    render(
      <ClinicalSummaryPanel
        summary={summary}
        eligibility={{
          case_id: "TCGA-05-4244",
          eligible_trials: 2,
          rationale: ["Exploratory eligibility heuristic match."],
          meta,
        }}
        survival={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open matched clinical trials" }));

    expect(await screen.findByRole("dialog", { name: "Matched clinical trials" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Stage III lung adenocarcinoma immunotherapy")).toBeInTheDocument();
      const link = screen.getByRole("link", { name: "Open NCT12345678 on ClinicalTrials.gov" });
      expect(link).toHaveAttribute("href", "https://clinicaltrials.gov/study/NCT12345678");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    });
    expect(apiClient.getClinicalTrialMatches).toHaveBeenCalledWith("TCGA-05-4244", {
      limit: 20,
      recruitingOnly: true,
    });
  });

  it("blocks non-http or non-ClinicalTrials links from becoming clickable", async () => {
    vi.spyOn(apiClient, "getClinicalTrialMatches").mockResolvedValue({
      case_id: "TCGA-05-4244",
      available: true,
      trials: [
        {
          title: "Unsafe javascript url",
          nct_id: "NCT00000001",
          status: "RECRUITING",
          phase: "Phase 1",
          match_score: 7,
          match_reasons: ["Test match reason"],
          rationale: "Test rationale",
          study_url: "javascript:alert('xss')",
        },
        {
          title: "Unsafe host url",
          nct_id: "NCT00000002",
          status: "RECRUITING",
          phase: "Phase 1",
          match_score: 7,
          match_reasons: ["Test match reason"],
          rationale: "Test rationale",
          study_url: "https://example.com/study/NCT00000002",
        },
      ],
      data_source: "modality_result",
      unavailable_reason: null,
      query_terms: ["lung cancer"],
      meta,
    });

    render(
      <ClinicalSummaryPanel
        summary={summary}
        eligibility={{
          case_id: "TCGA-05-4244",
          eligible_trials: 2,
          rationale: ["Exploratory eligibility heuristic match."],
          meta,
        }}
        survival={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open matched clinical trials" }));
    expect(await screen.findByRole("dialog", { name: "Matched clinical trials" })).toBeInTheDocument();

    expect(screen.getByLabelText("NCT00000001 study link unavailable")).toBeInTheDocument();
    expect(screen.getByLabelText("NCT00000002 study link unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open NCT00000001 on ClinicalTrials.gov" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open NCT00000002 on ClinicalTrials.gov" })).not.toBeInTheDocument();
  });

  it("supports keyboard open and escape close for the matched trials drawer", async () => {
    vi.spyOn(apiClient, "getClinicalTrialMatches").mockResolvedValue({
      case_id: "TCGA-05-4244",
      available: true,
      trials: [],
      data_source: "modality_result",
      unavailable_reason: null,
      query_terms: ["lung cancer"],
      meta,
    });

    render(
      <ClinicalSummaryPanel
        summary={summary}
        eligibility={{
          case_id: "TCGA-05-4244",
          eligible_trials: 1,
          rationale: ["Exploratory eligibility heuristic match."],
          meta,
        }}
        survival={null}
      />,
    );

    const card = screen.getByRole("button", { name: "Open matched clinical trials" });
    card.focus();
    fireEvent.keyDown(card, { key: "Enter" });

    expect(await screen.findByRole("dialog", { name: "Matched clinical trials" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Matched clinical trials" })).not.toBeInTheDocument();
    });
  });
});
