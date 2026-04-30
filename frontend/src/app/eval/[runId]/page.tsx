import { EvalRunDetail } from "@/components/eval/EvalRunDetail";

export default async function EvalRunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return (
    <div className="flex-1 max-w-7xl mx-auto w-full px-4 py-8">
      <EvalRunDetail runId={runId} />
    </div>
  );
}
