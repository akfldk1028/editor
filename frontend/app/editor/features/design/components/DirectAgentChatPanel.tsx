import React, { useEffect, useMemo, useState } from 'react';
import { DESIGN_FLOW_AGENTS } from './ag-light-flow/agents';

interface Props {
  disabled?: boolean;
  helperText?: string;
  selectedAgentId?: string;
  onSelectedAgentChange?: (agentId: string) => void;
  onSend: (targetAgent: string, message: string) => Promise<void>;
}

const PRESETS: Record<string, string> = {
  law_graph_agent: '이 후보의 법규 근거와 빠진 evidence를 rule_id 중심으로 확인해줘.',
  parking_agent: '주차 산정 대수, 연접 가능성, 차로/진입 조건을 다시 검토해줘.',
  massdsl_agent: '법규와 주차 evidence를 MassDSL verb sequence proposal로 구조화해줘.',
  maas_geometry_agent: '법규/주차 조건을 만족하도록 매스 repair operation 후보를 제안해줘.',
  grammar_critic_agent: '이 후보가 단순 extrusion 반복인지, 사선/테라스/분절 등 도형언어가 충분한지 검토해줘.',
  review_agent: '현재 evidence 기준으로 통과/보류/실패와 남은 리스크를 구조화해줘.',
};

export default function DirectAgentChatPanel({
  disabled = false,
  helperText,
  selectedAgentId,
  onSelectedAgentChange,
  onSend,
}: Props) {
  const agents = useMemo(() => DESIGN_FLOW_AGENTS.map((agent) => ({
    id: agent.participant.config.name,
    label: agent.mapping.fallbackLabel || agent.participant.label,
    description: agent.participant.config.description || agent.participant.description || '',
  })), []);
  const [localTargetAgent, setLocalTargetAgent] = useState(agents[0]?.id || '');
  const [message, setMessage] = useState(PRESETS[agents[0]?.id || ''] || '');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const targetAgent = selectedAgentId || localTargetAgent;
  const selectedAgent = agents.find((agent) => agent.id === targetAgent);

  useEffect(() => {
    if (!selectedAgentId) return;
    setMessage(PRESETS[selectedAgentId] || '');
    setError('');
  }, [selectedAgentId]);

  const updateTarget = (agentId: string) => {
    setLocalTargetAgent(agentId);
    onSelectedAgentChange?.(agentId);
    setMessage(PRESETS[agentId] || '');
    setError('');
  };

  const submit = async () => {
    const trimmed = message.trim();
    if (!targetAgent || !trimmed || disabled || sending) return;
    setSending(true);
    setError('');
    try {
      await onSend(targetAgent, trimmed);
      setMessage('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'agent 명령 전송 실패');
    } finally {
      setSending(false);
    }
  };

  return (
    <div style={{
      marginTop: 9,
      padding: 9,
      borderRadius: 8,
      border: '1px solid rgba(148,163,184,0.14)',
      background: 'rgba(2,6,23,0.42)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
        <div>
          <div style={{ color: '#dbeafe', fontSize: 11, fontWeight: 800 }}>
            Agent 직접 명령
          </div>
          <div style={{ color: '#64748b', fontSize: 9, marginTop: 2 }}>
            법규/주차/MassDSL/매스/문법검토 agent별로 따로 지시
          </div>
        </div>
        <select
          data-testid="direct-agent-target-select"
          value={targetAgent}
          onChange={(event) => updateTarget(event.target.value)}
          disabled={disabled || sending}
          style={{
            maxWidth: 168,
            borderRadius: 7,
            border: '1px solid rgba(96,165,250,0.2)',
            background: '#020617',
            color: '#bfdbfe',
            fontSize: 10,
            padding: '5px 7px',
          }}
        >
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.id}
            </option>
          ))}
        </select>
      </div>

      {selectedAgent && (
        <div style={{ marginTop: 7, color: '#94a3b8', fontSize: 9, lineHeight: 1.4 }}>
          <span style={{ color: '#5eead4', fontWeight: 800 }}>{selectedAgent.label}</span>
          {' · '}
          {selectedAgent.description}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 5, marginTop: 7 }}>
        {agents.map((agent) => (
          <button
            key={agent.id}
            type="button"
            data-testid={`direct-agent-preset-${agent.id}`}
            onClick={() => updateTarget(agent.id)}
            disabled={disabled || sending}
            style={{
              borderRadius: 7,
              border: targetAgent === agent.id ? '1px solid rgba(94,234,212,0.5)' : '1px solid rgba(148,163,184,0.14)',
              padding: '5px 6px',
              background: targetAgent === agent.id ? 'rgba(20,184,166,0.14)' : 'rgba(15,23,42,0.74)',
              color: targetAgent === agent.id ? '#99f6e4' : '#94a3b8',
              fontSize: 9,
              cursor: disabled || sending ? 'default' : 'pointer',
              textAlign: 'left',
            }}
          >
            {agent.id}
          </button>
        ))}
      </div>

      <textarea
        data-testid="direct-agent-message-input"
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        disabled={disabled || sending}
        rows={3}
        placeholder="선택한 agent에게 보낼 명령"
        style={{
          width: '100%',
          boxSizing: 'border-box',
          marginTop: 7,
          resize: 'vertical',
          minHeight: 62,
          borderRadius: 7,
          border: '1px solid rgba(148,163,184,0.16)',
          background: '#020617',
          color: '#cbd5e1',
          padding: 8,
          fontSize: 10,
          lineHeight: 1.45,
          outline: 'none',
        }}
      />
      <button
        type="button"
        data-testid="direct-agent-send-button"
        onClick={submit}
        disabled={disabled || sending || !message.trim()}
        style={{
          width: '100%',
          marginTop: 7,
          padding: '7px 0',
          borderRadius: 7,
          border: '1px solid rgba(96,165,250,0.2)',
          background: disabled || sending || !message.trim() ? 'rgba(255,255,255,0.03)' : 'rgba(37,99,235,0.16)',
          color: disabled || sending || !message.trim() ? '#64748b' : '#93c5fd',
          fontSize: 10,
          fontWeight: 800,
          cursor: disabled || sending || !message.trim() ? 'default' : 'pointer',
        }}
      >
        {sending ? `${targetAgent} 전송 중...` : `${targetAgent || 'agent'}에게 보내기`}
      </button>
      {(helperText || error) && (
        <div style={{ marginTop: 6, color: error ? '#fbbf24' : '#64748b', fontSize: 9, lineHeight: 1.4 }}>
          {error || helperText}
        </div>
      )}
    </div>
  );
}
