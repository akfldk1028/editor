'use client'

import { useEffect, useRef, useState } from 'react';
import { getRunContext, submitHealth, type RunContext } from './runs';
import type { ProjectBinding } from './projects';

export function HealthExecution({ project, onSubmitted }: { project: ProjectBinding; onSubmitted: (runId: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retrying, setRetrying] = useState(false);
  const pending = useRef<AbortController | null>(null);
  const attempt = useRef<{ key: string; context: RunContext } | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function submit() {
    if (pending.current) return;
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError('');
    try {
      if (!attempt.current) attempt.current = { key: crypto.randomUUID(), context: await getRunContext(project.project_id, controller.signal) };
      const run = await submitHealth(project.project_id, attempt.current.context, attempt.current.key, controller.signal);
      if (run.owner_project_id !== project.owner_project_id || run.branch_id !== project.branch_id ||
        run.request_id !== `editor:${project.project_id}:${attempt.current.key}`) throw new Error('접수된 실행의 프로젝트·요청 연결이 일치하지 않습니다.');
      if (!controller.signal.aborted) { attempt.current = null; setRetrying(false); onSubmitted(run.run_id); }
    } catch (e) {
      if (!controller.signal.aborted) { setError(e instanceof Error ? e.message : '실행 요청 실패'); setRetrying(attempt.current !== null); }
    } finally { pending.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="space-y-2 text-(--color-text-primary)">
    <button type="button" disabled={busy} onClick={() => void submit()} className="rounded border border-(--color-border-default) p-2">
      {busy ? '접수 확인 중…' : retrying ? '같은 연결 점검 요청 재확인' : '에이전트 연결 점검 실행'}
    </button>
    <p className="text-sm text-(--color-text-secondary)">현재는 연결 점검 실행을 지원합니다. 접수된 실행의 요청·응답을 대화와 흐름도에서 확인할 수 있습니다.</p>
    {error && <p role="alert" className="text-red-500">{error}</p>}
  </section>;
}
