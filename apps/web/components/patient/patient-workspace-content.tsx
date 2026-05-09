"use client";

import { useEffect, useState } from "react";

import type { CohortCaseSummary } from "@/lib/api-client";
import {
  type ClinicalPanelData,
  type IOImmunePanelData,
  type PathologyPanelData,
  type PatientWorkspaceSectionState,
  type TranscriptomicsPanelData,
  loadClinicalPanelData,
  loadIOImmunePanelData,
  loadPathologyPanelData,
  loadTranscriptomicsPanelData,
} from "@/lib/patient-workspace";

import { PatientHeader } from "./patient-header";
import { PatientWorkspacePanels } from "./patient-workspace-panels";

interface PatientWorkspaceContentProps {
  caseSummary: CohortCaseSummary;
}

function loadingState<TData>(): PatientWorkspaceSectionState<TData> {
  return {
    status: "loading",
    data: null,
  };
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }

  return "Unable to load panel data.";
}

export function PatientWorkspaceContent({ caseSummary }: PatientWorkspaceContentProps) {
  const caseId = caseSummary.case_id;

  const [pathologyState, setPathologyState] =
    useState<PatientWorkspaceSectionState<PathologyPanelData>>(() => loadingState());
  const [transcriptomicsState, setTranscriptomicsState] =
    useState<PatientWorkspaceSectionState<TranscriptomicsPanelData>>(() => loadingState());
  const [clinicalState, setClinicalState] =
    useState<PatientWorkspaceSectionState<ClinicalPanelData>>(() => loadingState());
  const [ioImmuneState, setIoImmuneState] =
    useState<PatientWorkspaceSectionState<IOImmunePanelData>>(() => loadingState());

  useEffect(() => {
    let cancelled = false;

    setPathologyState(loadingState());
    setTranscriptomicsState(loadingState());
    setClinicalState(loadingState());
    setIoImmuneState(loadingState());

    loadPathologyPanelData(caseId)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setPathologyState({ status: "ready", data });
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setPathologyState({
          status: "error",
          data: null,
          errorMessage: toErrorMessage(error),
        });
      });

    loadTranscriptomicsPanelData(caseId)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setTranscriptomicsState({ status: "ready", data });
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setTranscriptomicsState({
          status: "error",
          data: null,
          errorMessage: toErrorMessage(error),
        });
      });

    loadClinicalPanelData(caseId)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setClinicalState({ status: "ready", data });
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setClinicalState({
          status: "error",
          data: null,
          errorMessage: toErrorMessage(error),
        });
      });

    loadIOImmunePanelData(caseId)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setIoImmuneState({ status: "ready", data });
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setIoImmuneState({
          status: "error",
          data: null,
          errorMessage: toErrorMessage(error),
        });
      });

    return () => {
      cancelled = true;
    };
  }, [caseId]);

  return (
    <div className="min-w-0 space-y-4">
      <PatientHeader
        caseSummary={caseSummary}
        clinicalSummary={
          clinicalState.status === "ready"
            ? (clinicalState.data?.summary ?? null)
            : undefined
        }
        ioImmuneScore={
          ioImmuneState.status === "ready" ? ioImmuneState.data?.score : undefined
        }
        similarCases={
          ioImmuneState.status === "ready"
            ? (ioImmuneState.data?.similarCases ?? undefined)
            : undefined
        }
        similarCasesError={
          ioImmuneState.status === "ready" ? ioImmuneState.data?.similarCasesError : undefined
        }
        loading={clinicalState.status === "loading" || ioImmuneState.status === "loading"}
      />

      <PatientWorkspacePanels
        pathologyState={pathologyState}
        transcriptomicsState={transcriptomicsState}
        clinicalState={clinicalState}
        ioImmuneState={ioImmuneState}
      />
    </div>
  );
}
