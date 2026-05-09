import { AnalysisLiveShell } from "@/components/analysis/analysis-live-shell";
import { apiClient } from "@/lib/api-client";

interface AnalysisPageProps {
  params: Promise<{
    job_id: string;
  }>;
  searchParams?: Promise<{
    case_id?: string;
  }>;
}

export default async function AnalysisPage({ params, searchParams }: AnalysisPageProps) {
  const resolvedParams = await params;
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const job = await apiClient.getAnalysisJob(resolvedParams.job_id, resolvedSearchParams?.case_id);

  return <AnalysisLiveShell initialJob={job} />;
}
