import React, { useEffect, useMemo, useState } from 'react';
import { getAgLightBusLog, sendAgLightBusMessage } from '../lib/api-client';
import { COLLABORATION_STEPS } from '../lib/ag-light-collaboration';
import AGLightFlow from './ag-light-flow/AGLightFlow';
import type { AGLightMessage, AGLightRunStatus } from './ag-light-flow/types';
import DirectAgentChatPanel from './DirectAgentChatPanel';
import { BookLanguageFlow } from './book-language-flow/BookLanguageFlow';
import MASDialoguePanel from './MASDialoguePanel';
import { fetchMASDialogue, toAGLightMessages } from '../lib/mas-dialogue';

const DEFAULT_AGENT_FLOW_MESSAGES: AGLightMessage[] = [
  {
    from_agent: 'user',
    to_agent: 'design_orchestrator',
    message: '기본 프롬프트: PNU/후보가 들어오면 법규 그래프, 주차, MassDSL, MAAS 매스, 문법검토, 최종검토 에이전트가 순차 검토합니다.',
    event_type: 'prompt_template',
  },
];

const FLOW_AGENT_IDS = new Set([
  'user',
  'design_orchestrator',
  'law_graph_agent',
  'law_agent',
  'masterplan_agent',
  'master_plan_agent',
  'parking_agent',
  'massdsl_agent',
  'maas_geometry_agent',
  'grammar_critic_agent',
  'sunlight_agent',
  'datum_agent',
  'review_agent',
  'design_critic',
]);

const toFlowMessage = (event: {
  timestamp?: string;
  from_agent: string;
  to_agent: string;
  message: string;
  event_type?: string;
  metadata?: Record<string, unknown>;
}): AGLightMessage => ({
  timestamp: event.timestamp,
  from_agent: event.from_agent,
  to_agent: event.to_agent,
  message: event.message,
  event_type: event.event_type,
  metadata: event.metadata,
});

export default function DefaultAgentFlowPanel({
  pnu,
  status = 'idle',
}: {
  pnu?: string | null;
  status?: AGLightRunStatus;
}) {
  const pnuMessage = useMemo<AGLightMessage | null>(() => {
    if (!pnu) return null;
    return {
      from_agent: 'user',
      to_agent: 'design_orchestrator',
      message: `PNU ${pnu} 입력됨: 법규 그래프, 주차, MassDSL, 매스/기준면, 문법검토, 최종검토 순서로 전달 대기`,
      event_type: 'pnu_context',
      metadata: { pnu },
    };
  }, [pnu]);
  const [activeTab, setActiveTab] = useState<'mas_dialogue' | 'flow' | 'direct'>('mas_dialogue');
  const [manualMessages, setManualMessages] = useState<AGLightMessage[]>([]);
  const [busMessages, setBusMessages] = useState<AGLightMessage[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState('master_plan_agent');
  const messages = useMemo(
    () => [
      ...DEFAULT_AGENT_FLOW_MESSAGES,
      ...(pnuMessage ? [pnuMessage] : []),
      ...busMessages,
      ...manualMessages,
    ].slice(-24),
    [busMessages, manualMessages, pnuMessage],
  );

  useEffect(() => {
    let cancelled = false;
    const loadBus = async () => {
      try {
        const events = await getAgLightBusLog(30);
        const masTranscript = await fetchMASDialogue(pnu);
        if (cancelled) return;
        const masEvents = toAGLightMessages(masTranscript);
        const relevant = events
          .filter((event) => FLOW_AGENT_IDS.has(event.from_agent) || FLOW_AGENT_IDS.has(event.to_agent))
          .map(toFlowMessage);
        setBusMessages([...relevant, ...masEvents].slice(-16));
      } catch {
        if (!cancelled) setBusMessages([]);
      }
    };
    loadBus();
    const timer = window.setInterval(loadBus, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [pnu]);

  const sendDirectAgentMessage = async (targetAgent: string, message: string) => {
    const event: AGLightMessage = {
      from_agent: 'user',
      to_agent: targetAgent,
      message,
      event_type: 'direct_agent_command',
      metadata: { source: 'arr_design_default_flow' },
    };
    await sendAgLightBusMessage(event);
    setManualMessages((current) => [...current, event].slice(-8));
  };

  return (
    <div style={{
      border: '1px solid rgba(94,234,212,0.18)',
      borderRadius: 8,
      padding: 10,
      color: '#64748b',
      fontSize: 12,
      lineHeight: 1.6,
      background: 'rgba(15,23,42,0.72)',
    }}>
      <BookLanguageFlow pnu={pnu ?? undefined} compact />

      {/* Tab Selector */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 8,
        marginBottom: 10,
        marginTop: 6,
        paddingBottom: 8,
        borderBottom: '1px solid rgba(148,163,184,0.14)',
      }}>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            onClick={() => setActiveTab('mas_dialogue')}
            style={{
              background: activeTab === 'mas_dialogue' ? 'rgba(56,189,248,0.2)' : 'rgba(2,6,23,0.4)',
              border: activeTab === 'mas_dialogue' ? '1px solid #38bdf8' : '1px solid rgba(148,163,184,0.18)',
              color: activeTab === 'mas_dialogue' ? '#7dd3fc' : '#94a3b8',
              borderRadius: 6,
              padding: '4px 10px',
              fontSize: 11,
              fontWeight: 800,
              cursor: 'pointer',
            }}
          >
            🤖 MAS 실시간 대화 (A2A)
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('flow')}
            style={{
              background: activeTab === 'flow' ? 'rgba(94,234,212,0.2)' : 'rgba(2,6,23,0.4)',
              border: activeTab === 'flow' ? '1px solid #2dd4bf' : '1px solid rgba(148,163,184,0.18)',
              color: activeTab === 'flow' ? '#99f6e4' : '#94a3b8',
              borderRadius: 6,
              padding: '4px 10px',
              fontSize: 11,
              fontWeight: 800,
              cursor: 'pointer',
            }}
          >
            🕸️ 협업 Flow 토폴로지
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('direct')}
            style={{
              background: activeTab === 'direct' ? 'rgba(167,139,250,0.2)' : 'rgba(2,6,23,0.4)',
              border: activeTab === 'direct' ? '1px solid #a78bfa' : '1px solid rgba(148,163,184,0.18)',
              color: activeTab === 'direct' ? '#c4b5fd' : '#94a3b8',
              borderRadius: 6,
              padding: '4px 10px',
              fontSize: 11,
              fontWeight: 800,
              cursor: 'pointer',
            }}
          >
            💬 에이전트 직접 명령
          </button>
        </div>

        <span style={{
          color: '#fbbf24',
          fontSize: 9,
          border: '1px solid rgba(251,191,36,0.22)',
          borderRadius: 999,
          padding: '2px 7px',
          whiteSpace: 'nowrap',
        }}>
          프로젝트 실행 기록
        </span>
      </div>

      {/* Tab 1: MAS Dialogue Panel */}
      {activeTab === 'mas_dialogue' && (
        <MASDialoguePanel pnu={pnu} />
      )}

      {/* Tab 2: Flow Graph & Topology */}
      {activeTab === 'flow' && (
        <>
          <div style={{ marginBottom: 6, color: '#94a3b8', fontSize: 10 }}>
            법규(LawAgent :8301)·배치(MasterPlanAgent :8302) evidence와 BOOK·MassDSL 언어가 병렬로 진행되어 MAAS에서 합쳐지는 실행 경로
          </div>
          <AGLightFlow
            reviews={[]}
            messages={messages}
            status={status}
            viewMode="pattern"
            pnu={pnu}
            selectedAgentId={selectedAgentId}
            onSelectAgent={setSelectedAgentId}
          />
          <div
            data-testid="ag-light-collaboration-method"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
              gap: 6,
              marginTop: 8,
            }}
          >
            {COLLABORATION_STEPS.map((step) => (
              <button
                key={step.agent}
                type="button"
                onClick={() => setSelectedAgentId(step.agent)}
                style={{
                  minHeight: 56,
                  padding: '7px 8px',
                  borderRadius: 7,
                  border: selectedAgentId === step.agent
                    ? '1px solid rgba(94,234,212,0.5)'
                    : '1px solid rgba(148,163,184,0.14)',
                  background: selectedAgentId === step.agent
                    ? 'rgba(20,184,166,0.14)'
                    : 'rgba(2,6,23,0.38)',
                  textAlign: 'left',
                  cursor: 'pointer',
                }}
              >
                <div style={{ color: selectedAgentId === step.agent ? '#99f6e4' : '#bfdbfe', fontSize: 10, fontWeight: 900 }}>
                  {step.label}
                </div>
                <div style={{ color: '#60a5fa', fontSize: 9, marginTop: 2, fontFamily: 'ui-monospace, monospace' }}>
                  {step.agent}
                </div>
                <div style={{ color: '#94a3b8', fontSize: 9, lineHeight: 1.3, marginTop: 3 }}>
                  {step.output}
                </div>
              </button>
            ))}
          </div>
        </>
      )}

      {/* Tab 3: Direct Agent Chat */}
      {activeTab === 'direct' && (
        <DirectAgentChatPanel
          selectedAgentId={selectedAgentId}
          onSelectedAgentChange={setSelectedAgentId}
          onSend={sendDirectAgentMessage}
          helperText="선택한 에이전트(Lawagent, MasterPlanagent 등)로 A2A bus 명령을 직접 전달합니다."
        />
      )}

      <div style={{ marginTop: 8, color: '#94a3b8', fontSize: 10, lineHeight: 1.5 }}>
        후보를 선택하면 이 흐름에 실제 법규 evidence, 마스터플랜 배치 및 주차 구획, MassDSL proposal, MAAS 매스 검토 결과가 붙습니다.
      </div>
    </div>
  );
}
