import React from 'react';
import { useInteractiveDesign, formatMetric, type InteractiveDesignProps } from '../hooks/use-interactive-design';
import A2UISurfaceRenderer from './A2UISurfaceRenderer';
import { InteractiveAgentReview } from './InteractiveAgentReview';
import { InteractiveAestheticPanel } from './InteractiveAestheticPanel';

const EXAMPLES = [
  '북측 상부를 4단으로 자연스럽게 후퇴시켜줘. 용적률은 5% 이상 잃지 말고.',
  '도로 쪽 저층부를 포디움처럼 더 강하게 만들어줘.',
  '코어가 가운데라 답답해. 동측 외곽으로 붙일 수 있는지 봐줘.',
];

const InteractiveDesignPanel: React.FC<InteractiveDesignProps> = (props) => {
  const { jobId, design, massGeojson, sitePolygon, siteArea, pnu } = props;
  const {
    message, setMessage, result, preview, activePreviewId, loading, previewLoading, operationLoading, aestheticLoading, aestheticProvider, setAestheticProvider, aestheticStyle, setAestheticStyle, aesthetic, agHealth, agBusLog, agReviews, agTrace, agLoading, agError, selectedAgentId, setSelectedAgentId, error, runAgLightReview, sendDirectAgentMessage, submit, buildPreview, buildMaasVariants, selectPreview, applyOperation, generateAesthetic
  } = useInteractiveDesign(props);

  return (
    <div style={{
      marginTop: 0,
      padding: 10,
      borderRadius: 8,
      border: '1px solid rgba(96,200,255,0.16)',
      background: 'rgba(15,23,42,0.92)',
      minHeight: 'calc(100vh - 72px)',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: 8,
        alignItems: 'center',
        marginBottom: 8,
      }}>
        <div>
          <div style={{ color: '#dbeafe', fontSize: 12, fontWeight: 700 }}>
            상호소통 설계 수정
          </div>
          <div style={{ color: '#64748b', fontSize: 10, marginTop: 2 }}>
            대화형 수정 · MAAS 법규 후보
          </div>
        </div>
        <span style={{
          color: '#60c8ff',
          fontSize: 10,
          border: '1px solid rgba(96,200,255,0.24)',
          borderRadius: 999,
          padding: '2px 7px',
          whiteSpace: 'nowrap',
        }}>
          안 {design.id}
        </span>
      </div>

      <InteractiveAgentReview
        agHealth={agHealth}
        agBusLog={agBusLog}
        agReviews={agReviews}
        agTrace={agTrace}
        agLoading={agLoading}
        agError={agError}
        selectedAgentId={selectedAgentId}
        setSelectedAgentId={setSelectedAgentId}
        runAgLightReview={runAgLightReview}
        sendDirectAgentMessage={sendDirectAgentMessage}
        jobId={jobId}
        massGeojson={massGeojson}
        pnu={pnu}
      />

      <textarea
        value={message}
        onChange={e => setMessage(e.target.value)}
        placeholder="예: 북측 상부를 더 부드럽게 후퇴시켜줘. 용적률은 5% 이상 잃지 말고."
        rows={3}
        style={{
          width: '100%',
          boxSizing: 'border-box',
          resize: 'vertical',
          minHeight: 68,
          borderRadius: 7,
          border: '1px solid #243244',
          background: '#020617',
          color: '#cbd5e1',
          padding: 8,
          fontSize: 11,
          lineHeight: 1.45,
          outline: 'none',
        }}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 7 }}>
        {EXAMPLES.map(example => (
          <button
            key={example}
            type="button"
            onClick={() => setMessage(example)}
            style={{
              textAlign: 'left',
              border: 'none',
              borderRadius: 6,
              padding: '5px 7px',
              background: 'rgba(255,255,255,0.035)',
              color: '#94a3b8',
              fontSize: 10,
              cursor: 'pointer',
            }}
          >
            {example}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={submit}
        disabled={loading || !message.trim()}
        style={{
          width: '100%',
          marginTop: 8,
          padding: '8px 0',
          borderRadius: 7,
          border: 'none',
          cursor: loading || !message.trim() ? 'default' : 'pointer',
          fontSize: 11,
          fontWeight: 700,
          background: loading || !message.trim()
            ? 'rgba(96,200,255,0.08)'
            : 'rgba(96,200,255,0.16)',
          color: loading || !message.trim() ? '#64748b' : '#7dd3fc',
        }}
      >
        {loading ? '후보 생성 중...' : '수정 후보 만들기'}
      </button>

      <button
        type="button"
        onClick={buildMaasVariants}
        disabled={previewLoading || !massGeojson || !sitePolygon}
        style={{
          width: '100%',
          marginTop: 7,
          padding: '8px 0',
          borderRadius: 7,
          border: '1px solid rgba(94,234,212,0.22)',
          cursor: previewLoading || !massGeojson || !sitePolygon ? 'default' : 'pointer',
          fontSize: 11,
          fontWeight: 700,
          background: previewLoading || !massGeojson || !sitePolygon
            ? 'rgba(255,255,255,0.03)'
            : 'rgba(20,184,166,0.12)',
          color: previewLoading || !massGeojson || !sitePolygon ? '#64748b' : '#5eead4',
        }}
      >
        {previewLoading ? 'MAAS 계산 중...' : 'MAAS 법규 후보 바로 만들기'}
      </button>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
        gap: 6,
        marginTop: 7,
      }}>
	        {[
	          ['층+', { type: 'push_pull_face', target: { kind: 'top' }, delta_floors: 1 }],
	          ['층-', { type: 'push_pull_face', target: { kind: 'top' }, delta_floors: -1 }],
	          ['폭+', { type: 'scale_footprint', factor: 1.08 }],
	          ['폭-', { type: 'scale_footprint', factor: 0.92 }],
	        ].map(([label, op]) => (
          <button
            key={label as string}
            type="button"
            onClick={() => applyOperation(op as object)}
            disabled={operationLoading || !massGeojson || !sitePolygon}
            title="법규 envelope로 즉시 보정하고 FAR/BCR을 다시 계산합니다."
            style={{
              borderRadius: 7,
              border: '1px solid rgba(148,163,184,0.18)',
              padding: '7px 0',
              background: operationLoading ? 'rgba(255,255,255,0.03)' : 'rgba(15,23,42,0.86)',
              color: operationLoading ? '#64748b' : '#cbd5e1',
              fontSize: 11,
              fontWeight: 700,
              cursor: operationLoading || !massGeojson || !sitePolygon ? 'default' : 'pointer',
            }}
          >
            {label as string}
          </button>
        ))}
	      </div>

	      <div style={{
	        display: 'grid',
	        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
	        gap: 6,
	        marginTop: 6,
	      }}>
	        {[0, 1, 2, 3].map(edgeIndex => (
	          <button
	            key={edgeIndex}
	            type="button"
	            onClick={() => applyOperation({
	              type: 'offset_edge',
	              target: { kind: 'side', edge_index: edgeIndex },
	              delta_m: 1.5,
	            })}
	            disabled={operationLoading || !massGeojson || !sitePolygon}
	            title={`${edgeIndex + 1}번 외곽 edge를 1.5m 밀고 법규 envelope로 보정합니다.`}
	            style={{
	              borderRadius: 7,
	              border: '1px solid rgba(94,234,212,0.18)',
	              padding: '7px 0',
	              background: operationLoading ? 'rgba(255,255,255,0.03)' : 'rgba(20,184,166,0.08)',
	              color: operationLoading ? '#64748b' : '#99f6e4',
	              fontSize: 10,
	              fontWeight: 700,
	              cursor: operationLoading || !massGeojson || !sitePolygon ? 'default' : 'pointer',
	            }}
	          >
	            E{edgeIndex + 1}+
	          </button>
	        ))}
	      </div>

      <InteractiveAestheticPanel
        aestheticProvider={aestheticProvider}
        setAestheticProvider={setAestheticProvider}
        aestheticStyle={aestheticStyle}
        setAestheticStyle={setAestheticStyle}
        aestheticLoading={aestheticLoading}
        generateAesthetic={generateAesthetic}
        aesthetic={aesthetic}
        jobId={jobId}
        massGeojson={massGeojson}
      />

      {error && (
        <div style={{ marginTop: 8, color: '#fca5a5', fontSize: 11 }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ marginTop: 10 }}>
          <div style={{ color: '#94a3b8', fontSize: 10, marginBottom: 6 }}>
            해석: {result.interpreted_intents.join(', ') || 'none'}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            {result.candidates.map(candidate => (
              <div
                key={candidate.id}
                style={{
                  border: '1px solid rgba(148,163,184,0.14)',
                  borderRadius: 7,
                  padding: 8,
                  background: 'rgba(2,6,23,0.42)',
                }}
              >
                <div style={{ color: '#e2e8f0', fontSize: 11, fontWeight: 700 }}>
                  {candidate.title}
                </div>
                <div style={{ color: '#64748b', fontSize: 10, marginTop: 2 }}>
                  {candidate.intent} · {candidate.constraints.join(' / ')}
                </div>
                <ul style={{
                  margin: '6px 0 0',
                  paddingLeft: 16,
                  color: '#94a3b8',
                  fontSize: 10,
                  lineHeight: 1.45,
                }}>
                  {candidate.expected_effects.map(effect => (
                    <li key={effect}>{effect}</li>
                  ))}
                </ul>
                {candidate.risks.length > 0 && (
                  <div style={{ color: '#fbbf24', fontSize: 10, marginTop: 6 }}>
                    위험: {candidate.risks.join(', ')}
                  </div>
                )}
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={buildPreview}
            disabled={previewLoading || !sitePolygon || !siteArea}
            style={{
              width: '100%',
              marginTop: 8,
              padding: '8px 0',
              borderRadius: 7,
              border: '1px solid rgba(125,211,252,0.2)',
              cursor: previewLoading || !sitePolygon || !siteArea ? 'default' : 'pointer',
              fontSize: 11,
              fontWeight: 700,
              background: previewLoading || !sitePolygon || !siteArea
                ? 'rgba(255,255,255,0.03)'
                : 'rgba(20,184,166,0.12)',
              color: previewLoading || !sitePolygon || !siteArea ? '#64748b' : '#5eead4',
            }}
          >
            {previewLoading ? '미리보기 계산 중...' : '실제 매스 후보 계산'}
          </button>
          {result.notes.length > 0 && (
            <div style={{
              marginTop: 8,
              color: '#64748b',
              fontSize: 10,
              lineHeight: 1.45,
            }}>
              {result.notes.map(note => <div key={note}>· {note}</div>)}
            </div>
          )}
        </div>
      )}

      {preview && (
        <div style={{ marginTop: 10 }}>
          <div style={{ color: '#94a3b8', fontSize: 10, marginBottom: 6 }}>
            미리보기: {preview.algorithm} · {preview.building_type}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {preview.candidates.map(candidate => (
              <button
                key={candidate.id}
                type="button"
                onClick={() => selectPreview(candidate)}
                disabled={!candidate.mass_geojson}
                style={{
                  textAlign: 'left',
                  borderRadius: 7,
                  border: activePreviewId === candidate.id
                    ? '1px solid rgba(94,234,212,0.65)'
                    : '1px solid rgba(148,163,184,0.14)',
                  padding: 8,
                  background: activePreviewId === candidate.id
                    ? 'rgba(20,184,166,0.12)'
                    : 'rgba(2,6,23,0.42)',
                  cursor: candidate.mass_geojson ? 'pointer' : 'not-allowed',
                }}
              >
                <div style={{ color: '#e2e8f0', fontSize: 11, fontWeight: 700 }}>
                  {candidate.title}
                </div>
                <div style={{ color: candidate.feasible ? '#5eead4' : '#fbbf24', fontSize: 10, marginTop: 3 }}>
                  {candidate.feasible ? 'PASS' : 'CHECK'} · penalty {candidate.penalty.toFixed(3)}
                </div>
                <div style={{ color: '#94a3b8', fontSize: 10, marginTop: 5, lineHeight: 1.45 }}>
                  FAR {formatMetric(candidate.metrics.far)} · BCR {formatMetric(candidate.metrics.bcr)} ·
                  높이 {formatMetric(candidate.metrics.height)}m
                </div>
	                {candidate.notes.length > 0 && (
	                  <div style={{ color: '#64748b', fontSize: 10, marginTop: 5, lineHeight: 1.45 }}>
	                    {candidate.notes[0]}
	                  </div>
	                )}
	                {candidate.notes.some(note => note.includes('agent')) && (
	                  <div style={{ color: '#60a5fa', fontSize: 10, marginTop: 5, lineHeight: 1.45 }}>
	                    {candidate.notes.filter(note => note.includes('agent')).slice(0, 2).join(' · ')}
	                  </div>
	                )}
	              </button>
	            ))}
          </div>
	          {preview.notes.length > 0 && (
            <div style={{ marginTop: 8, color: '#64748b', fontSize: 10, lineHeight: 1.45 }}>
              {preview.notes.map(note => <div key={note}>· {note}</div>)}
            </div>
	          )}
	          <A2UISurfaceRenderer messages={preview.a2ui_messages} />
	        </div>
	      )}
    </div>
  );
};

export default InteractiveDesignPanel;
