import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { COLOR, STYLE, hexA } from '../lib/constants';
import type { LawArticlesResult, LawArticleItem } from '../lib/types';

interface LawArticlesListProps {
  lawArticles: LawArticlesResult | null | undefined;
  onSelectArticle?: (article: LawArticleItem) => void;
}

const MAX_PREVIEW = 5;
const MAX_TEXT_LEN = 160;

export const LawArticlesList = React.memo(function LawArticlesList({ lawArticles, onSelectArticle }: LawArticlesListProps) {
  const [open, setOpen] = useState(false);

  if (!lawArticles?.articles?.length) return null;

  const articles = lawArticles.articles;
  const total = lawArticles.total_count || articles.length;
  const preview = articles.slice(0, open ? articles.length : MAX_PREVIEW);

  return (
    <div style={{
      borderRadius: 12,
      background: 'rgba(255,255,255,0.015)',
      border: '1px solid rgba(255,255,255,0.04)',
      padding: '14px 14px 12px',
    }}>
      <button
        onClick={() => setOpen(prev => !prev)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, width: '100%',
          background: 'none', border: 'none', cursor: 'pointer',
          padding: 0, marginBottom: 10,
        }}
      >
        <ChevronDown style={{
          width: 12, height: 12, color: COLOR.textMuted,
          transition: 'transform 0.2s',
          transform: open ? 'rotate(180deg)' : 'rotate(0)',
        }} />
        <span style={{
          fontSize: 10, fontWeight: 700, color: COLOR.textMuted,
          letterSpacing: '0.1em', textTransform: 'uppercase' as const,
        }}>
          관련 법조항
        </span>
        <span style={{
          fontSize: 9, fontWeight: 700, color: COLOR.indigo,
          padding: '2px 6px', borderRadius: 4,
          background: 'rgba(129,140,248,0.08)',
          border: '1px solid rgba(129,140,248,0.15)',
        }}>
          {total}
        </span>
      </button>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {preview.map((a, i) => {
          const typeColor = COLOR.lawType[a.law_type || ''] || COLOR.textDim;
          const pct = Math.round((a.similarity || 0) * 100);
          const text = a.content.length > MAX_TEXT_LEN
            ? a.content.slice(0, MAX_TEXT_LEN) + '...'
            : a.content;

          return (
            <div
              key={a.hang_id || i}
              role={onSelectArticle ? 'button' : undefined}
              tabIndex={onSelectArticle ? 0 : undefined}
              onClick={() => onSelectArticle?.(a)}
              onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && onSelectArticle) { e.preventDefault(); onSelectArticle(a); } }}
              style={{
                position: 'relative',
                borderRadius: 8,
                background: 'rgba(255,255,255,0.01)',
                border: '1px solid rgba(255,255,255,0.04)',
                padding: '10px 12px',
                cursor: onSelectArticle ? 'pointer' : 'default',
                transition: 'all 0.15s ease',
                overflow: 'hidden',
              }}
              onMouseEnter={(e) => {
                if (!onSelectArticle) return;
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)';
                e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.04)';
                e.currentTarget.style.background = 'rgba(255,255,255,0.01)';
              }}
            >
              {/* Similarity accent bar at top */}
              <div style={{
                position: 'absolute', top: 0, left: 0, right: 0, height: 1,
                background: 'rgba(255,255,255,0.02)',
              }}>
                <div style={{
                  height: '100%', width: `${pct}%`,
                  background: `linear-gradient(90deg, ${hexA(typeColor, 0x60)}, ${hexA(typeColor, 0x20)})`,
                }} />
              </div>

              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: COLOR.text }}>
                  {a.law_name || ''}
                </span>
                {a.law_type && (
                  <span style={{
                    fontSize: 9, fontWeight: 600, color: typeColor,
                    padding: '1px 5px', borderRadius: 3,
                    background: hexA(typeColor, 0x10),
                  }}>
                    {a.law_type}
                  </span>
                )}
                {a.article && (
                  <span style={{ fontSize: 11, fontWeight: 500, color: COLOR.textMuted }}>{a.article}</span>
                )}
                <span style={{ flex: 1 }} />
                <span style={{
                  fontSize: 10, fontWeight: 600, color: COLOR.textDim,
                  fontFamily: STYLE.monoFont,
                }}>
                  {pct}%
                </span>
              </div>
              <p style={{
                margin: 0, marginTop: 5, fontSize: 12, color: COLOR.textMuted, lineHeight: 1.6,
                whiteSpace: 'pre-wrap', wordBreak: 'keep-all',
              }}>
                {text}
              </p>
            </div>
          );
        })}
      </div>

      {articles.length > MAX_PREVIEW && !open && (
        <button
          onClick={() => setOpen(true)}
          style={{
            marginTop: 8, background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 11, fontWeight: 600, color: COLOR.textMuted, padding: 0,
          }}
        >
          +{articles.length - MAX_PREVIEW}개 더 보기
        </button>
      )}
    </div>
  );
});
