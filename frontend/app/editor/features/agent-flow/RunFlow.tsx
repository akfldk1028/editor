'use client'

import { useMemo, useState } from 'react';
import AGLightFlow from './AGLightFlow';
import { toTranscript } from '../agent-dialogue/transcript';
import type { RunSummary } from '../agent-dialogue/runs';
import type { AGLightReview } from './types';

const reviews: AGLightReview[] = [];

export default function RunFlow({ projectId, run }: { projectId: string; run: RunSummary }) {
  const [selected, setSelected] = useState<string>();
  const transcript = useMemo(() => toTranscript(projectId, run), [projectId, run]);
  const messages = useMemo(() => transcript.messages.map(m => ({ from_agent: m.from_agent, to_agent: m.to_agent, message: m.message, metadata: m.payload })), [transcript]);
  const status = run.pending_input ? 'awaiting_input' : run.status === 'completed' ? 'complete' : run.status === 'failed' ? 'error' : run.status === 'running' ? 'active' : 'idle';
  const selectedMessages = transcript.messages.filter(m => m.from_agent === selected || m.to_agent === selected);
  return <section className="space-y-3">
    {!transcript.available && <p role="status">이 실행의 대화 기록을 제공받지 못했습니다.</p>}
    {transcript.truncated && <p role="status">일부 대화 기록이 생략되었습니다.</p>}
    {messages.length === 0 ? <p role="status">표시할 요청·응답 연결이 없습니다.</p> : <AGLightFlow reviews={reviews} messages={messages} status={status} viewMode="execution" selectedAgentId={selected} onSelectAgent={setSelected} />}
    {selected && <div className="space-y-2"><h2 className="text-heading-small">{selected} · 요청/응답</h2>
      {selectedMessages.map(m => <details key={m.id} className="rounded border border-(--color-border-default) p-3"><summary>{m.title} · {m.transport}</summary><pre className="whitespace-pre-wrap break-words text-sm mt-2">{m.message}</pre></details>)}
    </div>}
  </section>;
}
