import { CaseView } from "@/components/case-view/CaseView";

export default async function CasePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ replay?: string; runId?: string }>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  return <CaseView caseId={id} replay={sp.replay === "true"} evalRunId={sp.runId} />;
}
