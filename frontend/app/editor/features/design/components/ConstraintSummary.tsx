import React, { useState } from 'react';
import type { Constraint, LawSearchResult } from '../lib/types';

const LAW_TYPE_COLORS: Record<string, string> = {
  '\uBC95\uB960': '#3b82f6',
  '\uC2DC\uD589\uB839': '#7c3aed',
  '\uC2DC\uD589\uADDC\uCE59': '#d97706',
};

interface Props {
  constraints: Constraint[];
  lawArticles?: LawSearchResult | null;
}

const ConstraintSummary: React.FC<Props> = React.memo(({ constraints, lawArticles }) => {
  const [lawExpanded, setLawExpanded] = useState(false);

  if (constraints.length === 0 && !lawArticles?.total_count) return null;

  // Deduplicate law articles by full_id across all query groups
  const uniqueArticles = (() => {
    if (!lawArticles?.articles?.length) return [];
    const seen = new Set<string>();
    const result: { full_id: string; content: string; law_name: string; law_type: string; similarity: number }[] = [];
    for (const group of lawArticles.articles) {
      for (const a of group.results) {
        const id = a.full_id || a.content?.slice(0, 40);
        if (!seen.has(id)) {
          seen.add(id);
          result.push(a);
        }
      }
    }
    return result.sort((a, b) => (b.similarity || 0) - (a.similarity || 0)).slice(0, 15);
  })();

  return (
    <div style={{
      background: '#111827',
      borderRadius: 10,
      padding: 14,
      marginBottom: 10,
      border: '1px solid #1e293b',
    }}>
      {/* Constraints */}
      {constraints.length > 0 && (
        <>
          <h3 style={{
            color: '#64748b', fontSize: 10, fontWeight: 600,
            marginBottom: 8, letterSpacing: '0.08em',
          }}>
            CONSTRAINTS
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {constraints.map((c) => {
              const isLessThan = c.Requirement === 'Less than';
              const color = isLessThan ? '#f97316' : '#22c55e';
              return (
                <div
                  key={c.name}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '6px 10px',
                    background: '#0c1322',
                    borderRadius: 6,
                    fontSize: 12,
                    borderLeft: `3px solid ${color}`,
                  }}
                >
                  <span style={{ color: '#94a3b8' }}>{c.label}</span>
                  <span style={{
                    color,
                    fontWeight: 700,
                    fontSize: 12,
                    fontFamily: 'monospace',
                  }}>
                    {isLessThan ? '\u2264 ' : '\u2265 '}{c.val}{c.unit}
                  </span>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Law Articles */}
      {uniqueArticles.length > 0 && (
        <div style={{ marginTop: constraints.length > 0 ? 12 : 0 }}>
          <div
            style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              cursor: 'pointer', userSelect: 'none',
            }}
            onClick={() => setLawExpanded(prev => !prev)}
          >
            <h3 style={{
              color: '#64748b', fontSize: 10, fontWeight: 600,
              letterSpacing: '0.08em', margin: 0,
            }}>
              LAW ARTICLES ({uniqueArticles.length})
            </h3>
            <span style={{ color: '#475569', fontSize: 11 }}>
              {lawExpanded ? '\u25B2' : '\u25BC'}
            </span>
          </div>

          {lawExpanded && (
            <div style={{
              display: 'flex', flexDirection: 'column', gap: 3,
              marginTop: 8, maxHeight: 200, overflowY: 'auto',
            }}>
              {uniqueArticles.map((a, i) => {
                const typeColor = LAW_TYPE_COLORS[a.law_type] || '#64748b';
                return (
                  <div key={a.full_id || i} style={{
                    padding: '5px 8px',
                    background: '#0c1322',
                    borderRadius: 4,
                    fontSize: 11,
                    borderLeft: `2px solid ${typeColor}`,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                      <span style={{ color: typeColor, fontWeight: 600, fontSize: 10 }}>
                        {a.law_name}
                      </span>
                      <span style={{ color: '#334155', fontSize: 9, fontFamily: 'monospace' }}>
                        {((a.similarity || 0) * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div style={{
                      color: '#94a3b8', fontSize: 10, lineHeight: 1.4,
                      overflow: 'hidden', textOverflow: 'ellipsis',
                      display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const,
                    }}>
                      {a.content}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

ConstraintSummary.displayName = 'ConstraintSummary';
export default ConstraintSummary;
