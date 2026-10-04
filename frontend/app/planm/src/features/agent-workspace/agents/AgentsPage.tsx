import { useEffect, useState } from 'react';
import { listAgents } from '../api/client';
import type { AgentSummary } from '../api/types';
import './agents.css';

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [query, setQuery] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    listAgents(controller.signal).then((items) => {
      if (!controller.signal.aborted) setAgents(items);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '목록을 불러오지 못했습니다.');
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [attempt]);
  const search = query.trim().toLowerCase();
  const filtered = agents.filter((agent) =>
    [agent.agent_id, agent.label, ...agent.capabilities].join(' ').toLowerCase().includes(search));
  return <div className="agent-workspace">
    <header><div><h1>에이전트</h1><p>구현 상태와 서비스 연결 상태를 따로 확인합니다.</p></div>
      <button type="button" disabled={loading} onClick={() => setAttempt((value) => value + 1)}>새로고침</button></header>
    <input aria-label="에이전트 검색" placeholder="이름 또는 기능 검색" value={query} onChange={(event) => setQuery(event.target.value)} />
    {loading ? <p role="status">목록을 불러오는 중…</p> : error ? <p role="alert">{error}</p> :
      <div className="agent-workspace-grid">{filtered.map((agent) => <article key={agent.agent_id}>
        <h2>{agent.label}</h2><small>{agent.agent_id}</small>
        <dl><dt>구현</dt><dd>{agent.implementation_status}</dd><dt>연결</dt><dd>{agent.connection_status}</dd>
          <dt>마지막 확인</dt><dd>{agent.checked_at ?? '확인 기록 없음'}</dd></dl>
        <ul>{agent.capabilities.map((capability) => <li key={capability}>{capability}</li>)}</ul>
        {agent.evidence_ref && <p>근거: {agent.evidence_ref}</p>}
      </article>)}{filtered.length === 0 && <p>{search ? '검색 결과가 없습니다.' : '표시할 에이전트가 없습니다.'}</p>}</div>}
  </div>;
}
