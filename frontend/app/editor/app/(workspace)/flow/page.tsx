import DialoguePage from '@/features/agent-dialogue/DialoguePage';

export default async function Page({ searchParams }: { searchParams: Promise<{ project_id?: string; run_id?: string }> }) {
  const query = await searchParams;
  const projectId = typeof query.project_id === 'string' ? query.project_id : '';
  const runId = typeof query.run_id === 'string' ? query.run_id : '';
  return <DialoguePage key={`${projectId}:${runId}`} projectId={projectId} runId={runId} view="flow" />;
}
