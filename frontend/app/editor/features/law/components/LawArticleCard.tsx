import React, { useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { LawArticle } from '../lib/types';

interface LawArticleCardProps {
  article: LawArticle;
  index: number;
  selected?: boolean;
  onSelect?: (article: LawArticle) => void;
}

const ACCENT: Record<string, string> = {
  '법률': '#3b82f6', '시행령': '#7c3aed', '시행규칙': '#d97706',
};

const STAGE_LABELS: Record<string, string> = {
  vector_search: '벡터', vector: '벡터',
  relationship_search: '관계', relationship: '관계',
  graph_expansion: '확장', rne_expansion: '확장',
  exact_match: '정확', fulltext_keyword: '키워드',
  enrichment: '강화',
};

export const LawArticleCard = React.memo(function LawArticleCard({ article, index, selected, onSelect }: LawArticleCardProps) {
  const [expanded, setExpanded] = useState(false);
  const spotlightRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const isA2A = article.via_a2a === true;
  const percent = Math.round((article.similarity || 0) * 100);
  const lawName = article.law_name || article.hang_id?.split('_')[0] || '';
  const lawType = article.law_type || '';
  const articleNum = article.article || '';
  const accent = ACCENT[lawType] || '#64748b';
  const preview = article.content.length > 220 ? article.content.slice(0, 220) + '...' : article.content;
  const stages = [...new Set(article.stages.map((s) => STAGE_LABELS[s] || s))];

  return (
    <div
      ref={cardRef}
      onMouseMove={(e) => {
        if (!spotlightRef.current) return;
        const rect = e.currentTarget.getBoundingClientRect();
        spotlightRef.current.style.background =
          `radial-gradient(400px circle at ${e.clientX - rect.left}px ${e.clientY - rect.top}px, rgba(255,255,255,0.02), transparent 60%)`;
      }}
      onMouseEnter={() => {
        if (cardRef.current && !selected) {
          cardRef.current.style.background = 'rgba(255,255,255,0.03)';
          cardRef.current.style.transform = 'translateY(-1px)';
          cardRef.current.style.boxShadow = '0 4px 24px rgba(0,0,0,0.3)';
        }
      }}
      onMouseLeave={() => {
        if (cardRef.current) {
          cardRef.current.style.background = selected ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.015)';
          cardRef.current.style.transform = 'none';
          cardRef.current.style.boxShadow = '0 1px 2px rgba(0,0,0,0.1)';
        }
      }}
      onClick={() => onSelect?.(article)}
      style={{
        position: 'relative', overflow: 'hidden',
        borderRadius: 10,
        background: selected ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.015)',
        border: selected
          ? '1px solid rgba(255,255,255,0.1)'
          : '1px solid rgba(255,255,255,0.04)',
        transition: 'all 0.15s ease',
        cursor: onSelect ? 'pointer' : 'default',
        transform: 'none',
        boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
      }}
    >
      {/* Similarity bar — thin gradient at top */}
      <div style={{
        height: 2, borderRadius: '10px 10px 0 0', overflow: 'hidden',
        background: 'rgba(255,255,255,0.02)',
      }}>
        <div style={{
          height: '100%', width: `${percent}%`,
          background: `linear-gradient(90deg, ${accent}, ${accent}44)`,
          transition: 'width 0.4s ease-out',
        }} />
      </div>

      {/* Spotlight */}
      <div ref={spotlightRef} style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1,
      }} />

      <div style={{ position: 'relative', zIndex: 2, padding: '14px 18px 14px 16px', display: 'flex', gap: 14 }}>
        {/* Left accent + index */}
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
          paddingTop: 2, flexShrink: 0, width: 20,
        }}>
          <div style={{ width: 2, height: 20, borderRadius: 1, background: accent, opacity: 0.6 }} />
          <span style={{
            fontSize: 10, fontWeight: 600, color: '#475569',
            fontFamily: 'ui-monospace, "SF Mono", "Cascadia Mono", monospace',
          }}>
            {String(index).padStart(2, '0')}
          </span>
        </div>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Title line */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: '#e2e8f0', letterSpacing: '-0.01em' }}>
              {lawName}
            </span>
            {lawType && (
              <span style={{ fontSize: 11, color: '#64748b', fontWeight: 500 }}>{lawType}</span>
            )}
            {articleNum && (
              <span style={{ fontSize: 13, fontWeight: 600, color: '#94a3b8' }}>{articleNum}</span>
            )}
            {isA2A && (
              <span style={{
                fontSize: 10, fontWeight: 600, color: '#7c3aed',
                padding: '1px 6px', borderRadius: 4,
                background: 'rgba(124,58,237,0.1)',
              }}>
                A2A{article.source_domain ? ` · ${article.source_domain}` : ''}
              </span>
            )}
          </div>

          {/* Content */}
          <p style={{
            marginTop: 8, fontSize: 13.5, lineHeight: 1.75, color: '#b0b8c4',
            whiteSpace: 'pre-wrap', wordBreak: 'keep-all',
          }}>
            {expanded ? article.content : preview}
          </p>

          {article.content.length > 220 && (
            <button
              onClick={(e) => { e.stopPropagation(); setExpanded(prev => !prev); }}
              aria-expanded={expanded}
              style={{
                marginTop: 6, display: 'inline-flex', alignItems: 'center', gap: 3,
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 12, color: '#64748b', padding: 0,
                transition: 'color 0.15s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = '#94a3b8'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = '#64748b'; }}
            >
              <ChevronDown style={{
                width: 13, height: 13,
                transition: 'transform 0.2s',
                transform: expanded ? 'rotate(180deg)' : 'rotate(0)',
              }} />
              {expanded ? '접기' : '더보기'}
            </button>
          )}

          {/* Bottom line: stages + score */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
            {stages.length > 0 && (
              <span style={{ fontSize: 11, color: '#475569', fontWeight: 500 }}>
                {stages.join(' · ')}
              </span>
            )}
            <span style={{ flex: 1 }} />
            <span style={{
              fontSize: 11, fontWeight: 600, color: '#64748b',
              fontFamily: 'ui-monospace, "SF Mono", "Cascadia Mono", monospace',
            }}>
              {percent}%
            </span>
          </div>
        </div>
      </div>
    </div>
  );
});
