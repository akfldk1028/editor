import React from 'react';
import type { InteractiveDesignProps, useInteractiveDesign } from '../hooks/use-interactive-design';
import { requiredValue } from '../lib/required-value';

type Props = Pick<ReturnType<typeof useInteractiveDesign>, 'aestheticProvider' | 'setAestheticProvider' | 'aestheticStyle' | 'setAestheticStyle' | 'aestheticLoading' | 'generateAesthetic' | 'aesthetic'>
  & Pick<InteractiveDesignProps, 'jobId' | 'massGeojson'>;

export function InteractiveAestheticPanel({ aestheticProvider, setAestheticProvider, aestheticStyle, setAestheticStyle, aestheticLoading, generateAesthetic, aesthetic, jobId, massGeojson }: Props) {
  return (
      <div style={{
        marginTop: 10,
        padding: 9,
        borderRadius: 8,
        border: '1px solid rgba(167,139,250,0.18)',
        background: 'rgba(30,20,54,0.26)',
      }}>
        <div style={{ color: '#ddd6fe', fontSize: 11, fontWeight: 800, marginBottom: 3 }}>
          외관 이미지 생성
        </div>
        <div style={{ color: '#8b95a7', fontSize: 10, lineHeight: 1.45, marginBottom: 7 }}>
          법규 매스는 고정하고 재료, 창호 리듬, 분위기만 생성합니다.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 6 }}>
          <select
            value={aestheticProvider}
            onChange={e => setAestheticProvider(e.target.value as 'placeholder' | 'gpt-image' | 'nano-banana')}
            style={{
              width: '100%',
              borderRadius: 7,
              border: '1px solid #312e81',
              background: '#020617',
              color: '#c4b5fd',
              padding: '7px 8px',
              fontSize: 11,
              outline: 'none',
            }}
          >
            <option value="placeholder">Reference only</option>
            <option value="gpt-image">GPT Image</option>
            <option value="nano-banana">Nano Banana</option>
          </select>
          <textarea
            value={aestheticStyle}
            onChange={e => setAestheticStyle(e.target.value)}
            rows={2}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              resize: 'vertical',
              borderRadius: 7,
              border: '1px solid #312e81',
              background: '#020617',
              color: '#cbd5e1',
              padding: 8,
              fontSize: 10,
              lineHeight: 1.4,
              outline: 'none',
            }}
          />
          <button
            type="button"
            onClick={generateAesthetic}
            disabled={aestheticLoading || !jobId || !massGeojson}
            style={{
              width: '100%',
              padding: '8px 0',
              borderRadius: 7,
              border: '1px solid rgba(167,139,250,0.28)',
              cursor: aestheticLoading || !jobId || !massGeojson ? 'default' : 'pointer',
              fontSize: 11,
              fontWeight: 800,
              background: aestheticLoading || !jobId || !massGeojson ? 'rgba(255,255,255,0.03)' : 'rgba(124,58,237,0.18)',
              color: aestheticLoading || !jobId || !massGeojson ? '#64748b' : '#c4b5fd',
            }}
          >
            {aestheticLoading ? '외관 생성 중...' : '매스 기반 외관 생성'}
          </button>
        </div>
        {aesthetic && (
          <div style={{ marginTop: 8 }}>
            <div style={{ color: aesthetic.status === 'fail' ? '#fca5a5' : '#a7f3d0', fontSize: 10, marginBottom: 6 }}>
              {aesthetic.provider_result?.provider || aesthetic.job.provider} · {aesthetic.status}
              {aesthetic.provider_result?.status ? ` / ${aesthetic.provider_result.status}` : ''}
              {((aesthetic.provider_result?.metadata?.texture_bake as { status?: string } | undefined)?.status === 'skipped'
                || aesthetic.provider_result?.issues?.some(issue => issue.code === 'projection_panels_not_texture_ready')) ? ' / mesh skipped' : ''}
            </div>
            {aesthetic.reference?.url && (
              <a href={aesthetic.reference.url} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                <img
                  src={aesthetic.reference.url}
                  alt="Locked MAAS reference render"
                  style={{ width: '100%', borderRadius: 7, border: '1px solid rgba(148,163,184,0.16)', background: '#f8fafc' }}
                />
              </a>
            )}
            {aesthetic.provider_result?.assets?.[0]?.url && (
              <a href={aesthetic.provider_result.assets[0].url} target="_blank" rel="noreferrer" style={{ display: 'block', marginTop: 7 }}>
                <img
                  src={aesthetic.provider_result.assets[0].url}
                  alt="Generated facade concept"
                  style={{ width: '100%', borderRadius: 7, border: '1px solid rgba(148,163,184,0.16)' }}
                />
              </a>
            )}
            {aesthetic.provider_result?.issues?.length ? (
              <div style={{ color: '#fbbf24', fontSize: 10, lineHeight: 1.45, marginTop: 6 }}>
                {requiredValue(requiredValue(aesthetic.provider_result.issues[0]).message) || requiredValue(requiredValue(aesthetic.provider_result.issues[0]).code)}
              </div>
            ) : null}
            <div style={{ color: '#64748b', fontSize: 9, lineHeight: 1.45, marginTop: 6 }}>
              legal_status_effect: {aesthetic.job.evidence_policy?.legal_status_effect || 'none'}
            </div>
          </div>
        )}
      </div>

  );
}
