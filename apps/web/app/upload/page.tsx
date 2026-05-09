import { UploadShell } from "@/components/upload/upload-shell";
import { apiClient } from "@/lib/api-client";

interface UploadPageProps {
  searchParams?: Promise<{
    case_id?: string;
  }>;
}

export default async function UploadPage({ searchParams }: UploadPageProps) {
  const cases = await apiClient.listCohortCases();
  const resolvedSearchParams = searchParams ? await searchParams : undefined;

  return <UploadShell cases={cases} initialCaseId={resolvedSearchParams?.case_id} />;
}
