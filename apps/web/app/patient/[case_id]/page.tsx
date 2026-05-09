import { AgentChatRail } from "@/components/chat/agent-chat-rail";
import { PatientListSidebar } from "@/components/patient/patient-list-sidebar";
import { PatientWorkspaceContent } from "@/components/patient/patient-workspace-content";
import { loadPatientWorkspaceBootstrap } from "@/lib/patient-workspace";
import { redirect } from "next/navigation";

interface PatientPageProps {
  params: Promise<{
    case_id: string;
  }>;
}

export default async function PatientPage({ params }: PatientPageProps) {
  const resolvedParams = await params;
  const requestedCaseId = resolvedParams.case_id;
  const bootstrap = await loadPatientWorkspaceBootstrap(requestedCaseId);

  if (bootstrap.selectedCase.case_id !== requestedCaseId) {
    redirect(`/patient/${bootstrap.selectedCase.case_id}`);
  }

  return (
    <div className="relative left-1/2 w-screen max-w-none -translate-x-1/2 px-4 lg:px-6">
      <div className="grid gap-4 xl:grid-cols-[clamp(220px,18vw,300px)_minmax(0,1fr)_clamp(280px,24vw,420px)] xl:items-start">
        <PatientListSidebar cases={bootstrap.cases} selectedCaseId={bootstrap.selectedCase.case_id} />

        <div className="min-w-0">
          <PatientWorkspaceContent caseSummary={bootstrap.selectedCase} />
        </div>

        <div className="min-w-0">
          <AgentChatRail caseId={bootstrap.selectedCase.case_id} />
        </div>
      </div>
    </div>
  );
}
