import React from 'react';
import type { InteractiveDesignProps, useInteractiveDesign } from '../hooks/use-interactive-design';
import { COLLABORATION_STEPS, statusColor } from '../lib/ag-light-collaboration';
import AGLightFlow from './ag-light-flow/AGLightFlow';
import DirectAgentChatPanel from './DirectAgentChatPanel';

type Props = Pick<ReturnType<typeof useInteractiveDesign>, 'agHealth' | 'agBusLog' | 'agReviews' | 'agTrace' | 'agLoading' | 'agError' | 'selectedAgentId' | 'setSelectedAgentId' | 'runAgLightReview' | 'sendDirectAgentMessage'>
  & Pick<InteractiveDesignProps, 'jobId' | 'massGeojson' | 'pnu'>;

export function InteractiveAgentReview({ agHealth, agBusLog, agReviews, agTrace, agLoading, agError, selectedAgentId, setSelectedAgentId, runAgLightReview, sendDirectAgentMessage, jobId, massGeojson, pnu }: Props) {
  return (
      <div style={{
        marginBottom: 10,
        padding: 9,
        borderRadius: 8,
        border: '1px solid rgba(34,197,94,0.18)',
        background: 'rgba(6,78,59,0.16)',
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          marginBottom: 7,
        }}>
          <div>
            <div style={{ color: '#d1fae5', fontSize: 11, fontWeight: 800 }}>
              AG-light React Flow
            </div>
            <div style={{ color: '#6b7280', fontSize: 9, marginTop: 2 }}>
              JSON_MODULES 법규 · 주차 · MassDSL · 매스 · 문법검토 · 최종검토 협업 그래프
            </div>
          </div>
          <span style={{
            color: agHealth?.status ? '#5eead4' : '#fbbf24',
            fontSize: 9,
            border: '1px solid rgba(94,234,212,0.18)',
            borderRadius: 999,
            padding: '2px 7px',
            whiteSpace: 'nowrap',
          }}>
            {agHealth?.status ? `ON · log ${agHealth.components?.bus?.log_count ?? agBusLog.length}` : 'CHECK'}
          </span>
        </div>
        <div
          data-testid="ag-light-collaboration-method"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
            gap: 6,
            marginBottom: 8,
          }}
        >
          {COLLABORATION_STEPS.map((step) => (
            <button
              key={step.agent}
              type="button"
              onClick={() => setSelectedAgentId(step.agent)}
              style={{
                minHeight: 58,
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
        <button
          type="button"
          onClick={runAgLightReview}
          disabled={agLoading || !jobId || !massGeojson}
          style={{
            width: '100%',
            padding: '8px 0',
            borderRadius: 7,
            border: '1px solid rgba(94,234,212,0.24)',
            cursor: agLoading || !jobId || !massGeojson ? 'default' : 'pointer',
            fontSize: 11,
            fontWeight: 800,
            background: agLoading || !jobId || !massGeojson ? 'rgba(255,255,255,0.03)' : 'rgba(20,184,166,0.14)',
            color: agLoading || !jobId || !massGeojson ? '#64748b' : '#99f6e4',
          }}
        >
          {agLoading ? '협업 검토 중...' : '현재 안 AG-light 검토 시작'}
        </button>
        <AGLightFlow
          reviews={agReviews}
          messages={agBusLog}
          status={agHealth?.status ? 'complete' : 'idle'}
          pnu={pnu}
          selectedAgentId={selectedAgentId}
          onSelectAgent={setSelectedAgentId}
        />
        <DirectAgentChatPanel
          selectedAgentId={selectedAgentId}
          onSelectedAgentChange={setSelectedAgentId}
          onSend={sendDirectAgentMessage}
          helperText="선택한 agent에게 직접 명령을 보내고 최근 bus에 반영합니다."
        />
        {agError && (
          <div style={{ marginTop: 6, color: '#fbbf24', fontSize: 10, lineHeight: 1.4 }}>
            {agError}
          </div>
        )}
        {agTrace.length > 0 && (
          <div
            data-testid="ag-light-reasoning-trace"
            style={{
              marginTop: 8,
              padding: 8,
              borderRadius: 8,
              border: '1px solid rgba(96,165,250,0.16)',
              background: 'rgba(2,6,23,0.38)',
            }}
          >
            <div style={{ color: '#bfdbfe', fontSize: 10, fontWeight: 800, marginBottom: 6 }}>
              Agent reasoning trace
            </div>
            {agTrace.map(trace => (
              <div
                key={`trace-${trace.agent}`}
                data-testid={`ag-light-trace-${trace.agent}`}
                style={{
                  marginTop: 6,
                  padding: '7px 8px',
                  borderRadius: 7,
                  border: '1px solid rgba(148,163,184,0.12)',
                  background: 'rgba(15,23,42,0.58)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <span style={{ color: statusColor(trace.status), fontSize: 10, fontWeight: 900 }}>
                    {trace.label}
                  </span>
                  <span style={{ color: '#64748b', fontSize: 9, fontFamily: 'ui-monospace, monospace' }}>
                    {trace.agent}
                  </span>
                </div>
                <div style={{ marginTop: 4, color: '#e2e8f0', fontSize: 10, fontWeight: 700, lineHeight: 1.35 }}>
                  {trace.summary}
                </div>
                <div style={{ marginTop: 4, color: '#94a3b8', fontSize: 9, lineHeight: 1.45 }}>
                  <span style={{ color: '#5eead4', fontWeight: 800 }}>참조</span>
                  {' '}
                  {trace.refs.length ? trace.refs.join(' · ') : '근거 없음'}
                </div>
                <div style={{ marginTop: 3, color: '#94a3b8', fontSize: 9, lineHeight: 1.45 }}>
                  <span style={{ color: '#fbbf24', fontWeight: 800 }}>공식</span>
                  {' '}
                  {trace.formula || '공식/룰 텍스트 없음'}
                </div>
                <div style={{ marginTop: 3, color: '#cbd5e1', fontSize: 9, lineHeight: 1.45 }}>
                  <span style={{ color: '#93c5fd', fontWeight: 800 }}>판단</span>
                  {' '}
                  {trace.decision}
                </div>
              </div>
            ))}
          </div>
        )}
        {agReviews.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 5 }}>
            {agReviews.map(review => (
              <div
                key={review.agent}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '54px 1fr',
                  gap: 7,
                  padding: '6px 7px',
                  borderRadius: 7,
                  border: '1px solid rgba(148,163,184,0.12)',
                  background: 'rgba(2,6,23,0.36)',
                }}
              >
                <div style={{ color: statusColor(review.status), fontSize: 10, fontWeight: 800 }}>
                  {review.label}
                </div>
                <div>
                  <div style={{ color: '#dbeafe', fontSize: 10, fontWeight: 700, lineHeight: 1.35 }}>
                    {review.summary}
                  </div>
                  <div style={{ color: '#64748b', fontSize: 9, lineHeight: 1.35, marginTop: 2 }}>
                    {review.detail}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        {agBusLog.length > 0 && (
          <div style={{
            marginTop: 8,
            paddingTop: 7,
            borderTop: '1px solid rgba(148,163,184,0.12)',
          }}>
            <div style={{ color: '#94a3b8', fontSize: 9, marginBottom: 5 }}>
              최근 bus
            </div>
            {agBusLog.slice(-3).reverse().map((event, index) => (
              <div key={`${event.timestamp}-${index}`} style={{ color: '#64748b', fontSize: 9, lineHeight: 1.45 }}>
                <span style={{ color: '#93c5fd' }}>{event.from_agent}</span>
                {' -> '}
                <span>{event.to_agent}</span>
                {' · '}
                {event.message.slice(0, 58)}{event.message.length > 58 ? '...' : ''}
              </div>
            ))}
          </div>
        )}
      </div>

  );
}
