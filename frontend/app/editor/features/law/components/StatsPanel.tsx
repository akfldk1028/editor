import type { SearchStats } from '../lib/types';

interface StatsPanelProps {
  stats?: SearchStats;
  responseTime?: number;
  domainName?: string;
  a2aDomains?: string[];
}

export function StatsPanel({ stats, responseTime, domainName, a2aDomains }: StatsPanelProps) {
  if (!stats) return null;
  const total = stats.total || 0;
  const hasA2A = stats.a2a_collaboration_triggered && a2aDomains && a2aDomains.length > 0;

  const vPct = total > 0 ? (stats.vector_count / total) * 100 : 0;
  const rPct = total > 0 ? (stats.relationship_count / total) * 100 : 0;
  const gPct = total > 0 ? ((stats.graph_expansion_count || 0) / total) * 100 : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '0 4px' }}>
      {/* Summary line */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        fontSize: 12, color: '#64748b',
      }}>
        <span style={{ fontWeight: 600, color: '#94a3b8' }}>{total}건</span>
        {responseTime != null && (
          <span style={{ fontFamily: 'ui-monospace, "SF Mono", monospace', fontSize: 11 }}>
            {Math.round(responseTime)}ms
          </span>
        )}
        {domainName && <span>{domainName}</span>}
        {hasA2A && <span style={{ color: '#7c3aed' }}>A2A {a2aDomains.length}개</span>}
      </div>

      {/* Distribution bar */}
      {total > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{
            display: 'flex', height: 3, borderRadius: 2, overflow: 'hidden',
            background: 'rgba(255,255,255,0.03)',
          }}>
            {vPct > 0 && <div style={{ width: `${vPct}%`, background: '#64748b', transition: 'width 0.4s' }} />}
            {rPct > 0 && <div style={{ width: `${rPct}%`, background: '#818cf8', transition: 'width 0.4s' }} />}
            {gPct > 0 && <div style={{ width: `${gPct}%`, background: '#a78bfa', transition: 'width 0.4s' }} />}
          </div>
          <div style={{ display: 'flex', gap: 12, fontSize: 10, color: '#475569' }}>
            {stats.vector_count > 0 && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ width: 4, height: 4, borderRadius: 1, background: '#64748b' }} />
                벡터 {stats.vector_count}
              </span>
            )}
            {stats.relationship_count > 0 && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ width: 4, height: 4, borderRadius: 1, background: '#818cf8' }} />
                관계 {stats.relationship_count}
              </span>
            )}
            {(stats.graph_expansion_count || 0) > 0 && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ width: 4, height: 4, borderRadius: 1, background: '#a78bfa' }} />
                확장 {stats.graph_expansion_count}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
