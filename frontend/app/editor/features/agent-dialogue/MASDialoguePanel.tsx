'use client'

import { useState } from 'react';
import type { MASCollaborationTranscript, MASDialogueMessage } from './transcript';

interface Props {
  transcript: MASCollaborationTranscript;
  loading: boolean;
  onRefresh: () => void;
  className?: string;
}

export default function MASDialoguePanel({ transcript, loading, onRefresh, className = '' }: Props) {
  const [expandedPayloads, setExpandedPayloads] = useState<Record<string, boolean>>({});
  const [filterAgent, setFilterAgent] = useState('all');
  const togglePayload = (id: string) => {
    setExpandedPayloads((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const filteredMessages = transcript.messages.filter((m) => {
    if (filterAgent === 'all') return true;
    return m.from_agent === filterAgent || m.to_agent === filterAgent;
  });

  const getAgentToneColor = (agentId: string) => {
    if (agentId.includes('law')) return { bg: 'rgba(16,185,129,0.12)', border: '#10b981', text: '#6ee7b7' };
    if (agentId.includes('masterplan')) return { bg: 'rgba(14,165,233,0.12)', border: '#0ea5e9', text: '#7dd3fc' };
    if (agentId.includes('solver') || agentId.includes('geometry')) return { bg: 'rgba(245,158,11,0.12)', border: '#f59e0b', text: '#fde68a' };
    return { bg: 'rgba(139,92,246,0.12)', border: '#8b5cf6', text: '#c4b5fd' };
  };

  const getStatusBadge = (status: MASDialogueMessage['status']) => {
    if (status === 'fail') return { label: 'FAIL', color: '#ef4444', bg: 'rgba(239,68,68,0.2)' };
    if (status === 'check') return { label: 'CHECK', color: '#f59e0b', bg: 'rgba(245,158,11,0.2)' };
    return { label: 'INFO', color: '#38bdf8', bg: 'rgba(56,189,248,0.2)' };
  };

  return (
    <div
      className={className}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        background: 'rgba(15,23,42,0.85)',
        border: '1px solid rgba(94,234,212,0.25)',
        borderRadius: 10,
        padding: 14,
        color: '#e2e8f0',
        fontSize: 12,
      }}
    >
      {/* 1. Header Bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 8,
          borderBottom: '1px solid rgba(148,163,184,0.15)',
          paddingBottom: 10,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 900, color: '#f8fafc' }}>
              🤖 Multi-Agent System (MAS) 협업 대화
            </span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 800,
                padding: '2px 8px',
                borderRadius: 999,
                background: transcript.verdict === 'completed' ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)',
                color: transcript.verdict === 'completed' ? '#34d399' : '#f87171',
                border: `1px solid ${transcript.verdict === 'completed' ? 'rgba(16,185,129,0.4)' : 'rgba(239,68,68,0.4)'}`,
              }}
            >
              {transcript.verdict}
            </span>
            <span
              style={{
                fontSize: 10,
                color: '#94a3b8',
                background: 'rgba(30,41,59,0.6)',
                padding: '2px 6px',
                borderRadius: 4,
              }}
            >
              실행 상태 · {transcript.verdict}
            </span>
          </div>
          <div style={{ color: '#94a3b8', fontSize: 11, marginTop: 3 }}>
            프로젝트: {transcript.project_id} · 실행: {transcript.session_id}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select
            aria-label="대화 에이전트 필터"
            value={filterAgent}
            onChange={(e) => setFilterAgent(e.target.value)}
            style={{
              background: '#020617',
              border: '1px solid rgba(148,163,184,0.2)',
              color: '#cbd5e1',
              borderRadius: 6,
              padding: '4px 8px',
              fontSize: 11,
            }}
          >
            <option value="all">전체 에이전트 ({transcript.messages.length}턴)</option>
            {transcript.participants.map((p) => (
              <option key={p.agent_id} value={p.agent_id}>
                {p.name} ({p.role.slice(0, 12)}...)
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            style={{
              background: 'rgba(56,189,248,0.15)',
              border: '1px solid rgba(56,189,248,0.3)',
              color: '#38bdf8',
              borderRadius: 6,
              padding: '4px 10px',
              fontSize: 11,
              cursor: 'pointer',
              fontWeight: 700,
            }}
          >
            {loading ? '동기화 중...' : '새로고침'}
          </button>
        </div>
      </div>

      {!transcript.available && <p role="status">이 실행의 대화 기록을 제공받지 못했습니다.</p>}
      {transcript.truncated && <p role="status">대화 기록 일부가 생략되었습니다.</p>}
      {transcript.available && transcript.messages.length === 0 && <p role="status">아직 저장된 대화가 없습니다.</p>}
      {/* 2. Participating Mesh Agents Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 6,
        }}
      >
        {transcript.participants.map((p) => {
          const tone = getAgentToneColor(p.agent_id);
          return (
            <div
              key={p.agent_id}
              style={{
                background: tone.bg,
                border: `1px solid ${tone.border}`,
                borderRadius: 6,
                padding: '6px 10px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 800, color: tone.text, fontSize: 11 }}>
                  {p.name}
                </span>
                <span style={{ fontSize: 9, color: '#94a3b8', fontFamily: 'monospace' }}>
                  {p.role}
                </span>
              </div>
              <div style={{ color: '#cbd5e1', fontSize: 10, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {p.role}
              </div>
            </div>
          );
        })}
      </div>

      {/* 3. Turn-by-turn Dialogue Timeline */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
          maxHeight: 520,
          overflowY: 'auto',
          paddingRight: 4,
        }}
      >
        {filteredMessages.map((m) => {
          const tone = getAgentToneColor(m.from_agent);
          const statusBadge = getStatusBadge(m.status);
          const hasPayload = m.payload && Object.keys(m.payload).length > 0;
          const isExpanded = !!expandedPayloads[m.id];

          return (
            <div
              key={m.id}
              style={{
                background: 'rgba(2,6,23,0.55)',
                border: `1px solid ${tone.border}44`,
                borderLeft: `4px solid ${tone.border}`,
                borderRadius: 6,
                padding: '10px 12px',
                cursor: 'default',
              }}
            >
              {/* Turn Top Meta */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 6,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      background: '#1e293b',
                      color: '#94a3b8',
                      fontSize: 9,
                      fontWeight: 800,
                      borderRadius: 3,
                      padding: '1px 5px',
                    }}
                  >
                    Step {m.step}
                  </span>
                  <span style={{ color: tone.text, fontWeight: 800, fontSize: 11 }}>
                    {m.sender_title}
                  </span>
                  <span style={{ color: '#64748b', fontSize: 10 }}>
                    ────▶ {m.to_agent}
                  </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      fontSize: 9,
                      padding: '1px 6px',
                      borderRadius: 999,
                      background: statusBadge.bg,
                      color: statusBadge.color,
                      fontWeight: 800,
                    }}
                  >
                    {statusBadge.label}
                  </span>
                  <span style={{ color: '#64748b', fontSize: 9 }}>
                    {m.transport}
                  </span>
                </div>
              </div>

              {/* Title & Headline */}
              <div style={{ fontWeight: 800, color: '#f1f5f9', fontSize: 11, marginBottom: 4 }}>
                {m.title}
              </div>

              {/* Message Content */}
              <div
                style={{
                  color: '#cbd5e1',
                  fontSize: 11,
                  lineHeight: 1.5,
                  whiteSpace: 'pre-wrap',
                }}
              >
                {m.message}
              </div>

              {/* Collapsible Payload Section */}
              {hasPayload && (
                <div style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      togglePayload(m.id);
                    }}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: '#38bdf8',
                      cursor: 'pointer',
                      fontSize: 10,
                      padding: 0,
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                    }}
                  >
                    {isExpanded ? '▼ 기록 메타데이터 접기' : '▶ 기록 메타데이터 (JSON) 보기'}
                  </button>

                  {isExpanded && (
                    <pre
                      style={{
                        background: '#090d16',
                        border: '1px solid rgba(148,163,184,0.15)',
                        borderRadius: 4,
                        padding: 8,
                        marginTop: 4,
                        fontSize: 10,
                        color: '#93c5fd',
                        fontFamily: 'ui-monospace, monospace',
                        overflowX: 'auto',
                        maxHeight: 180,
                      }}
                    >
                      {JSON.stringify(m.payload, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 4. Bottom Summary Banner */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 8,
          background: 'rgba(2,6,23,0.4)',
          border: '1px solid rgba(94,234,212,0.15)',
          borderRadius: 6,
          padding: '8px 12px',
          fontSize: 11,
        }}
      >
        <div>기록 {transcript.messages.length}건 · 접수 작업 {transcript.receipt_task_ids.length}건</div>
        <div>목표: {transcript.goal} · 추가 입력: {transcript.pending_input ? '필요' : '없음'}</div>
        <div>통신 완료는 설계·법규 검증 완료를 의미하지 않습니다.</div>
      </div>
    </div>
  );
}
