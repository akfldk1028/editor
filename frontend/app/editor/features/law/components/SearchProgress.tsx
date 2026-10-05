import React from 'react';
import { Loader2, XCircle } from 'lucide-react';
import type { SearchProgress, SearchStage } from '../hooks/use-law-search-stream';

const STAGE_NAMES: Record<string, string> = {
  exact_match: '정확 일치',
  vector_search: '벡터 검색',
  relationship_search: '관계 검색',
  rne_expansion: '그래프 확장',
  enrichment: '결과 강화',
};

export function SearchProgressIndicator({ progress }: { progress: SearchProgress }) {
  const pct = Math.round((progress.progress || 0) * 100);
  const stageName = progress.stage ? (STAGE_NAMES[progress.stage] || progress.stage) : '';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Stage + percentage */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Loader2 style={{ width: 14, height: 14, color: '#64748b', animation: 'spin 1s linear infinite', flexShrink: 0 }} />
        <span style={{ fontSize: 13, color: '#94a3b8', fontWeight: 500 }}>
          {progress.stage_name || stageName || '검색 준비 중...'}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: '#475569', fontVariantNumeric: 'tabular-nums' }}>{pct}%</span>
      </div>

      {/* Progress bar — thin, clean */}
      <div
        role="progressbar"
        aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}
        aria-label="검색 진행률"
        style={{ height: 2, borderRadius: 1, background: 'rgba(255,255,255,0.04)', overflow: 'hidden' }}
      >
        <div style={{
          height: '100%', borderRadius: 1,
          background: '#64748b',
          width: `${pct}%`, transition: 'width 0.4s ease-out',
        }} />
      </div>

      {progress.node_count != null && (
        <span style={{ fontSize: 11, color: '#334155' }}>
          {progress.node_count.toLocaleString()} 노드 탐색 중
        </span>
      )}
    </div>
  );
}

export function SearchErrorIndicator({ message }: { message: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '4px 0' }}>
      <XCircle style={{ width: 16, height: 16, color: '#dc2626', flexShrink: 0, marginTop: 1 }} />
      <div>
        <p style={{ fontSize: 13, fontWeight: 600, color: '#f87171' }}>검색 실패</p>
        <p style={{ fontSize: 12, color: '#475569', marginTop: 2 }}>{message}</p>
      </div>
    </div>
  );
}

export function SearchCompleteHeader({
  resultCount, responseTime, domainName,
}: {
  resultCount: number;
  responseTime: number;
  domainName?: string;
}) {
  const parts = [`${resultCount}건`];
  if (domainName) parts.push(domainName);
  parts.push(`${Math.round(responseTime)}ms`);

  return (
    <p style={{ fontSize: 13, color: '#64748b', fontWeight: 500 }}>
      {parts.join(' · ')}
    </p>
  );
}
