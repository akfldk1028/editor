/**
 * AgentProgressPanel — 에이전트 협업 타임라인 UI
 *
 * 6에이전트 대화를 실시간 표시:
 * - 에이전트별 색상 배지 + 아이콘
 * - 메시지 내용 (접기/펼치기)
 * - 그래디언트 진행률 바
 * - Phase 인디케이터 + shimmer
 *
 * 스타일: inline hex (LawChat 패턴 동일)
 */

import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { AgentMessage, AgentAnalysisEvent } from '../lib/types';

const AGENT_COLORS: Record<string, { color: string; bg: string; label: string; icon: string }> = {
  land_analyst:        { color: '#60a5fa', bg: 'rgba(59,130,246,0.12)', label: '토지분석', icon: '🏗' },
  legal_interpreter:   { color: '#a78bfa', bg: 'rgba(139,92,246,0.12)', label: '법률해석', icon: '⚖' },
  synthesizer:         { color: '#34d399', bg: 'rgba(16,185,129,0.12)', label: '종합분석', icon: '📊' },
};

function getAgentInfo(source: string) {
  const key = source.toLowerCase().replace(/\s+/g, '_');
  return AGENT_COLORS[key] || { color: '#94a3b8', bg: 'rgba(148,163,184,0.1)', label: source, icon: '🤖' };
}

interface Props {
  messages: AgentMessage[];
  event: AgentAnalysisEvent | null;
  progress: number;
  isRunning: boolean;
  report: string | null;
  runSummary: { duration: number; total_tokens: number; turn_count: number } | null;
  onStop?: () => void;
}

function AgentProgressPanel({ messages, event, progress, isRunning, report, runSummary, onStop }: Props) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [showFullReport, setShowFullReport] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    if (scrollRef.current && isRunning) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length, isRunning]);

  const phaseName = (() => {
    if (!event) return '';
    if (event.status === 'analyzing') return event.phase_name;
    if (event.status === 'quick_done') return '빠른 분석 완료';
    if (event.status === 'agent') return getAgentInfo(event.agent).label;
    if (event.status === 'complete') return '분석 완료';
    if (event.status === 'error') return '오류 발생';
    return '';
  })();

  const pct = Math.round(progress * 100);
  const isDone = event?.status === 'complete';
  const isError = event?.status === 'error';

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
      style={{
        background: 'rgba(15,15,30,0.85)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderRadius: 16,
        border: '1px solid rgba(99,102,241,0.15)',
        overflow: 'hidden',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05)',
      }}
    >
      {/* ── Top accent line (animated gradient) ── */}
      <div style={{
        height: 2,
        background: isRunning
          ? 'linear-gradient(90deg, #3b82f6, #8b5cf6, #ec4899, #3b82f6)'
          : isDone
            ? 'linear-gradient(90deg, #10b981, #34d399)'
            : isError
              ? 'linear-gradient(90deg, #ef4444, #f87171)'
              : 'linear-gradient(90deg, #3b82f6, #8b5cf6)',
        backgroundSize: isRunning ? '200% 100%' : '100% 100%',
        animation: isRunning ? 'shimmer 2s linear infinite' : 'none',
      }} />

      <div style={{ padding: '14px 16px' }}>
        {/* ── Header ── */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {/* Status dot */}
            <div style={{ position: 'relative' }}>
              <div style={{
                width: 10, height: 10, borderRadius: '50%',
                background: isRunning ? '#10b981' : isDone ? '#6366f1' : isError ? '#ef4444' : '#64748b',
              }} />
              {isRunning && (
                <div style={{
                  position: 'absolute', inset: -3,
                  borderRadius: '50%',
                  border: '2px solid rgba(16,185,129,0.4)',
                  animation: 'pulse 1.5s ease-in-out infinite',
                }} />
              )}
            </div>
            <span style={{
              color: '#f1f5f9', fontWeight: 600, fontSize: 14, letterSpacing: '-0.01em',
            }}>
              AI 에이전트 심화 분석
            </span>
            {isDone && (
              <span style={{
                background: 'rgba(16,185,129,0.15)', color: '#34d399',
                padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 600,
              }}>
                완료
              </span>
            )}
          </div>
          {isRunning && onStop && (
            <button
              onClick={onStop}
              style={{
                background: 'rgba(239,68,68,0.1)',
                border: '1px solid rgba(239,68,68,0.25)',
                borderRadius: 8, padding: '5px 12px',
                color: '#f87171', cursor: 'pointer',
                fontSize: 12, fontWeight: 500,
                transition: 'all 0.2s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.2)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.1)'; }}
            >
              중단
            </button>
          )}
        </div>

        {/* ── Progress bar ── */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500 }}>
              {phaseName}
            </span>
            <span style={{
              color: isDone ? '#34d399' : '#94a3b8',
              fontSize: 12, fontWeight: 600, fontFeatureSettings: '"tnum"',
            }}>
              {pct}%
            </span>
          </div>
          <div style={{
            height: 6, borderRadius: 3, overflow: 'hidden',
            background: 'rgba(255,255,255,0.06)',
          }}>
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.6, ease: 'easeOut' }}
              style={{
                height: '100%', borderRadius: 3,
                background: isDone
                  ? 'linear-gradient(90deg, #10b981, #34d399)'
                  : isError
                    ? 'linear-gradient(90deg, #ef4444, #f87171)'
                    : 'linear-gradient(90deg, #3b82f6, #8b5cf6, #a78bfa)',
                boxShadow: isRunning ? '0 0 12px rgba(99,102,241,0.4)' : 'none',
              }}
            />
          </div>
        </div>

        {/* ── Agent messages timeline ── */}
        <AnimatePresence>
          {messages.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              transition={{ duration: 0.3 }}
              ref={scrollRef}
              style={{
                maxHeight: 280, overflowY: 'auto', marginBottom: report ? 14 : 0,
                scrollbarWidth: 'thin', scrollbarColor: 'rgba(99,102,241,0.3) transparent',
              }}
            >
              {messages.map((msg, i) => {
                const info = getAgentInfo(msg.agent);
                const expanded = expandedIdx === i;
                const truncated = msg.content.length > 120;
                const displayContent = expanded || !truncated
                  ? msg.content
                  : msg.content.slice(0, 120) + '...';

                return (
                  <motion.div
                    key={`${msg.turn}-${msg.agent}`}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.25, delay: 0.05 }}
                    style={{
                      display: 'flex', gap: 10, padding: '10px 0',
                      borderBottom: i < messages.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                    }}
                  >
                    {/* Timeline dot + line */}
                    <div style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'center',
                      flexShrink: 0, width: 20, paddingTop: 2,
                    }}>
                      <div style={{
                        width: 8, height: 8, borderRadius: '50%',
                        background: info.color,
                        boxShadow: `0 0 8px ${info.color}66`,
                      }} />
                      {i < messages.length - 1 && (
                        <div style={{
                          flex: 1, width: 1, marginTop: 4,
                          background: `linear-gradient(to bottom, ${info.color}44, transparent)`,
                        }} />
                      )}
                    </div>

                    <div style={{ flex: 1, minWidth: 0 }}>
                      {/* Badge */}
                      <div style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        background: info.bg,
                        border: `1px solid ${info.color}33`,
                        borderRadius: 6, padding: '2px 8px', marginBottom: 4,
                      }}>
                        <span style={{ fontSize: 10 }}>{info.icon}</span>
                        <span style={{ color: info.color, fontSize: 11, fontWeight: 600 }}>
                          {info.label}
                        </span>
                        <span style={{ color: '#475569', fontSize: 10 }}>
                          Turn {msg.turn}
                        </span>
                      </div>

                      {/* Content */}
                      <p style={{
                        color: '#c8d0dc', fontSize: 13, lineHeight: 1.55,
                        margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                      }}>
                        {displayContent}
                      </p>
                      {truncated && (
                        <button
                          onClick={() => setExpandedIdx(expanded ? null : i)}
                          style={{
                            background: 'none', border: 'none', color: '#818cf8',
                            cursor: 'pointer', fontSize: 11, fontWeight: 500,
                            padding: '3px 0', marginTop: 2,
                          }}
                        >
                          {expanded ? '접기' : '더 보기'}
                        </button>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Final report ── */}
        <AnimatePresence>
          {report && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
              style={{
                background: 'linear-gradient(135deg, rgba(99,102,241,0.08), rgba(139,92,246,0.06))',
                borderRadius: 12, padding: 14,
                border: '1px solid rgba(99,102,241,0.15)',
              }}
            >
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{
                    width: 4, height: 16, borderRadius: 2,
                    background: 'linear-gradient(to bottom, #6366f1, #8b5cf6)',
                  }} />
                  <span style={{ color: '#a5b4fc', fontSize: 12, fontWeight: 600, letterSpacing: '0.02em' }}>
                    최종 보고서
                  </span>
                </div>
                {report.length > 300 && (
                  <button
                    onClick={() => setShowFullReport(prev => !prev)}
                    style={{
                      background: 'rgba(99,102,241,0.1)', border: '1px solid rgba(99,102,241,0.2)',
                      borderRadius: 6, padding: '3px 8px',
                      color: '#818cf8', cursor: 'pointer', fontSize: 11, fontWeight: 500,
                    }}
                  >
                    {showFullReport ? '요약' : '전체 보기'}
                  </button>
                )}
              </div>
              <p style={{
                color: '#e2e8f0', fontSize: 13, lineHeight: 1.65, margin: 0,
                whiteSpace: 'pre-wrap',
                maxHeight: showFullReport ? 'none' : 200,
                overflow: showFullReport ? 'visible' : 'hidden',
                maskImage: !showFullReport && report.length > 300
                  ? 'linear-gradient(to bottom, black 70%, transparent 100%)'
                  : 'none',
                WebkitMaskImage: !showFullReport && report.length > 300
                  ? 'linear-gradient(to bottom, black 70%, transparent 100%)'
                  : 'none',
              }}>
                {report}
              </p>
              {runSummary && (
                <div style={{
                  display: 'flex', gap: 16, marginTop: 10, paddingTop: 10,
                  borderTop: '1px solid rgba(99,102,241,0.1)',
                }}>
                  {[
                    { label: '소요시간', value: `${Math.round(runSummary.duration)}초` },
                    { label: '에이전트 턴', value: `${runSummary.turn_count}회` },
                  ].map(({ label, value }) => (
                    <div key={label} style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                      <span style={{ color: '#64748b', fontSize: 11 }}>{label}</span>
                      <span style={{
                        color: '#a5b4fc', fontSize: 13, fontWeight: 600,
                        fontFeatureSettings: '"tnum"',
                      }}>
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Error fallback ── */}
        <AnimatePresence>
          {isError && event && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              style={{
                background: 'rgba(239,68,68,0.08)', borderRadius: 10,
                padding: '10px 12px', marginTop: 10,
                border: '1px solid rgba(239,68,68,0.15)',
              }}
            >
              <p style={{ color: '#fca5a5', fontSize: 12, margin: 0, lineHeight: 1.5 }}>
                {event.message}
              </p>
              {'fallback_to_quick' in event && event.fallback_to_quick && (
                <p style={{ color: '#64748b', fontSize: 11, margin: '4px 0 0' }}>
                  빠른 분석 결과는 위에 표시됩니다.
                </p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

export default React.memo(AgentProgressPanel);
