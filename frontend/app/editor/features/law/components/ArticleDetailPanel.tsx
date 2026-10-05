import React, { useEffect, useState } from 'react';
import { X, Copy, Check, Loader2, AlertCircle } from 'lucide-react';
import { motion } from 'framer-motion';
import type { LawArticle, ArticleDetail } from '../lib/types';
import { getArticle } from '../lib/law-api-client';

interface ArticleDetailPanelProps {
  article: LawArticle;
  onClose: () => void;
}

const LAW_TYPE_COLORS: Record<string, { accent: string; bg: string; text: string }> = {
  '법률':     { accent: '#3b82f6', bg: '#3b82f615', text: '#60a5fa' },
  '시행령':   { accent: '#7c3aed', bg: '#7c3aed15', text: '#a78bfa' },
  '시행규칙': { accent: '#d97706', bg: '#d9770615', text: '#fbbf24' },
};
const DEFAULT_LAW = { accent: '#94a3b8', bg: 'rgba(255,255,255,0.06)', text: '#94a3b8' };

export const ArticleDetailPanel = React.memo(function ArticleDetailPanel({
  article, onClose,
}: ArticleDetailPanelProps) {
  const [detail, setDetail] = useState<ArticleDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const lawType = article.law_type || '';
  const lc = LAW_TYPE_COLORS[lawType] || DEFAULT_LAW;
  const fullId = article.hang_id;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);

    getArticle(fullId).then((data) => {
      if (!cancelled) {
        setDetail(data);
        setLoading(false);
      }
    }).catch((err) => {
      if (!cancelled) {
        setError(err.message);
        setLoading(false);
      }
    });

    return () => { cancelled = true; };
  }, [fullId]);

  const handleCopy = async () => {
    if (!detail) return;
    const text = detail.hangs.map((h) => {
      let line = `${h.number ? `제${h.number}항` : ''} ${h.content}`;
      if (h.hos.length > 0) {
        line += '\n' + h.hos.map((ho) => `  ${ho.number}. ${ho.content}`).join('\n');
      }
      return line;
    }).join('\n\n');
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <motion.div
      initial={{ x: 40, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: 40, opacity: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      style={{
        display: 'flex', flexDirection: 'column', height: '100%',
        background: '#111', position: 'relative',
        borderLeft: '1px solid rgba(255,255,255,0.04)',
      }}
    >
      {/* Header */}
      <div style={{
        flexShrink: 0, padding: '14px 18px',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#64748b' }}>조문 원문</span>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              onClick={handleCopy}
              disabled={!detail}
              style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '6px 10px', borderRadius: 8, border: 'none', cursor: detail ? 'pointer' : 'default',
                background: copied ? 'rgba(5,150,105,0.15)' : 'rgba(255,255,255,0.06)',
                fontSize: 11, fontWeight: 600, color: copied ? '#34d399' : '#94a3b8',
              }}
            >
              {copied ? <Check style={{ width: 12, height: 12 }} /> : <Copy style={{ width: 12, height: 12 }} />}
              {copied ? '복사됨' : '전체 복사'}
            </button>
            <button
              onClick={onClose}
              aria-label="닫기"
              style={{
                width: 28, height: 28, borderRadius: 8, border: 'none',
                background: 'rgba(255,255,255,0.06)', cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              <X style={{ width: 14, height: 14, color: '#94a3b8' }} />
            </button>
          </div>
        </div>

        {/* Law info */}
        {detail && (
          <>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
              <span style={{ padding: '4px 10px', borderRadius: 8, background: `${lc.accent}15`, fontSize: 12, fontWeight: 700, color: lc.text }}>
                {detail.law_name}
              </span>
              <span style={{ padding: '4px 8px', borderRadius: 8, background: 'rgba(255,255,255,0.06)', fontSize: 11, fontWeight: 600, color: '#94a3b8' }}>
                {detail.law_type}
              </span>
              {detail.jo && (
                <span style={{ padding: '4px 8px', borderRadius: 8, background: 'rgba(22,163,74,0.1)', fontSize: 11, fontWeight: 700, color: '#4ade80' }}>
                  제{detail.jo.number}
                </span>
              )}
            </div>
            {detail.jo?.title && (
              <p style={{ fontSize: 16, fontWeight: 800, color: '#e2e8f0' }}>
                제{detail.jo.number} ({detail.jo.title})
              </p>
            )}
            <p style={{ marginTop: 4, fontSize: 11, color: '#64748b' }}>
              {detail.hang_count}개 항 · {detail.ho_count}개 호
            </p>
          </>
        )}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
        {loading && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '60px 0', gap: 12 }}>
            <Loader2 style={{ width: 24, height: 24, color: '#6366f1', animation: 'spin 1s linear infinite' }} />
            <span style={{ fontSize: 13, color: '#64748b' }}>조문 불러오는 중...</span>
          </div>
        )}

        {error && (
          <div style={{
            display: 'flex', alignItems: 'flex-start', gap: 10,
            padding: 16, borderRadius: 12, background: 'rgba(220,38,38,0.06)', border: '1px solid rgba(220,38,38,0.2)',
          }}>
            <AlertCircle style={{ width: 16, height: 16, color: '#dc2626', flexShrink: 0, marginTop: 2 }} />
            <div>
              <p style={{ fontSize: 13, fontWeight: 700, color: '#fca5a5' }}>조문 로드 실패</p>
              <p style={{ fontSize: 12, color: '#f87171', marginTop: 2 }}>{error}</p>
              {/* Fallback: show the single article content */}
              <div style={{ marginTop: 12, padding: 12, borderRadius: 8, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(220,38,38,0.2)' }}>
                <p style={{ fontSize: 13, lineHeight: 1.8, color: '#cbd5e1' }}>{article.content}</p>
              </div>
            </div>
          </div>
        )}

        {detail && !loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {detail.hangs.map((hang, i) => {
              const isMatch = hang.full_id === fullId;
              return (
                <div
                  key={hang.full_id}
                  id={isMatch ? 'matched-hang' : undefined}
                  style={{
                    padding: 16, borderRadius: 14,
                    background: isMatch ? 'rgba(99,102,241,0.06)' : 'rgba(255,255,255,0.02)',
                    border: isMatch ? '1px solid rgba(99,102,241,0.2)' : '1px solid rgba(255,255,255,0.04)',
                    transition: 'all 0.2s',
                    ...(isMatch ? { animation: 'matchGlow 3s ease-in-out infinite' } : {}),
                  }}
                >
                  {/* Hang header */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <span style={{
                      padding: '2px 8px', borderRadius: 6,
                      background: isMatch ? '#6366f1' : 'rgba(255,255,255,0.08)',
                      fontSize: 11, fontWeight: 700,
                      color: isMatch ? '#fff' : '#94a3b8',
                    }}>
                      {hang.number ? `제${hang.number}항` : `항`}
                    </span>
                    {isMatch && (
                      <span style={{
                        padding: '2px 6px', borderRadius: 6,
                        background: 'rgba(251,191,36,0.15)', fontSize: 10, fontWeight: 700, color: '#fbbf24',
                      }}>
                        검색 결과
                      </span>
                    )}
                  </div>

                  {/* Hang content */}
                  <p style={{
                    fontSize: 13, lineHeight: 1.9, color: '#cbd5e1',
                    whiteSpace: 'pre-wrap', wordBreak: 'keep-all',
                  }}>
                    {hang.content}
                  </p>

                  {/* HOs */}
                  {hang.hos.length > 0 && (
                    <div style={{ marginTop: 10, paddingLeft: 16, borderLeft: '2px solid rgba(255,255,255,0.06)' }}>
                      {hang.hos.map((ho) => (
                        <div key={ho.full_id} style={{ marginBottom: 6 }}>
                          <p style={{ fontSize: 12, lineHeight: 1.7, color: '#94a3b8' }}>
                            <span style={{ fontWeight: 700, color: '#64748b' }}>{ho.number}.</span>{' '}
                            {ho.content}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
        @keyframes matchGlow { 0%, 100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.05); } 50% { box-shadow: 0 0 20px 4px rgba(99,102,241,0.1); } }
      `}</style>
    </motion.div>
  );
});
