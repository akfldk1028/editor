/**
 * HeroSearch — 법규 검색 빈 상태(empty state) 히어로 화면.
 *
 * Perplexity 스타일: 중앙 검색바 + 예제 쿼리 + 연결 상태.
 * 메시지가 없을 때만 표시, 첫 검색 시 사라짐.
 *
 * 스타일: inline hex (Tailwind CSS 변수 충돌 회피)
 */

import React from 'react';
import {
  Search,
  Loader2,
  ArrowUp,
  ArrowRight,
  Command,
  Radio,
  WifiOff,
} from 'lucide-react';
import { motion } from 'framer-motion';
import type { DomainInfo } from '../lib/types';
import { glassInputHandlers } from '../lib/glass-input';

const EXAMPLES = [
  '개발행위 허가 요건',
  '건폐율 용적률 제한',
  '용도지역 변경 절차',
  '일조권 높이제한',
  '농지 전용 허가',
];

/** 부드러운 이징 (ease-out-quart) */
const EASE = [0.25, 0.46, 0.45, 0.94] as const;

interface HeroSearchProps {
  /** 현재 입력값 (controlled) */
  query: string;
  /** 입력값 변경 */
  onQueryChange: (value: string) => void;
  /** Enter/버튼 클릭 시 검색 실행 */
  onSearch: (query: string) => void;
  /** 검색 중 여부 (입력 비활성화) */
  busy: boolean;
  /** 백엔드 연결 상태 */
  isConnected: boolean;
  /** 실시간 스트리밍 모드 */
  streamingMode: boolean;
  /** 스트리밍 모드 토글 */
  onToggleStreaming: () => void;
  /** 검색 도메인 목록 */
  domains: DomainInfo[];
  /** 도메인 로딩 중 */
  domainsLoading: boolean;
  /** 선택된 도메인 ID */
  selectedDomainId: string | null;
  /** 도메인 선택 변경 */
  onDomainChange: (id: string | null) => void;
  /** input ref (외부에서 focus 제어) */
  inputRef: React.RefObject<HTMLInputElement | null>;
}

export function HeroSearch({
  query, onQueryChange, onSearch, busy,
  isConnected, streamingMode, onToggleStreaming,
  domains, domainsLoading, selectedDomainId, onDomainChange,
  inputRef,
}: HeroSearchProps) {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSearch(query);
    }
  };

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: '0 24px 80px',
      position: 'relative', overflow: 'hidden',
    }}>
      {/* 배경 글로우 */}
      <div style={{
        position: 'absolute', top: '15%', left: '30%',
        width: 500, height: 500, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(99,102,241,0.06) 0%, transparent 70%)',
        filter: 'blur(60px)', pointerEvents: 'none',
      }} />
      <div style={{
        position: 'absolute', top: '40%', right: '25%',
        width: 400, height: 400, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(139,92,246,0.04) 0%, transparent 70%)',
        filter: 'blur(60px)', pointerEvents: 'none',
      }} />

      {/* 타이틀 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: EASE }}
        style={{ textAlign: 'center', position: 'relative', zIndex: 1 }}
      >
        <h1 style={{
          fontSize: 44, fontWeight: 700, letterSpacing: '-0.035em', lineHeight: 1.1,
          background: 'linear-gradient(135deg, #e2e8f0 0%, #94a3b8 100%)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
        }}>
          무엇을 찾고 계신가요?
        </h1>
        <p style={{ marginTop: 12, fontSize: 15, color: '#475569', fontWeight: 400, letterSpacing: '-0.01em' }}>
          법률 · 조문 · 관련 근거 검색
        </p>
      </motion.div>

      {/* 검색바 */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.15, ease: EASE }}
        style={{ width: '100%', maxWidth: 640, marginTop: 40, position: 'relative', zIndex: 1 }}
      >
        <div style={{ position: 'relative' }}>
          <Search style={{ position: 'absolute', left: 20, top: '50%', transform: 'translateY(-50%)', width: 20, height: 20, color: '#475569' }} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="건폐율, 용적률, 개발행위 허가..."
            disabled={busy}
            aria-label="법규 검색어 입력"
            style={{
              width: '100%', padding: '18px 56px 18px 52px',
              borderRadius: 16, fontSize: 16, color: '#e2e8f0', fontWeight: 400,
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              outline: 'none', transition: 'all 0.2s',
              ...(busy ? { opacity: 0.5 } : {}),
            }}
            onFocus={glassInputHandlers.onFocus}
            onBlur={glassInputHandlers.onBlur}
          />
          <button
            onClick={() => onSearch(query)}
            disabled={!query.trim() || busy}
            style={{
              position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
              width: 40, height: 40, borderRadius: 12,
              border: 'none', cursor: query.trim() && !busy ? 'pointer' : 'default',
              background: query.trim() && !busy ? '#fff' : 'rgba(255,255,255,0.06)',
              color: query.trim() && !busy ? '#0a0a12' : '#475569',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'all 0.2s',
            }}
          >
            {busy
              ? <Loader2 style={{ width: 18, height: 18, animation: 'spin 1s linear infinite' }} />
              : <ArrowUp style={{ width: 18, height: 18 }} />
            }
          </button>
        </div>

        {/* 인라인 컨트롤 (연결·스트리밍·도메인) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, paddingLeft: 4 }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 4,
            fontSize: 12, color: isConnected ? '#475569' : '#dc2626',
          }}>
            <div style={{
              width: 6, height: 6, borderRadius: '50%',
              background: isConnected ? '#22c55e' : '#dc2626',
            }} />
            {isConnected ? '연결됨' : '오프라인'}
          </div>

          <span style={{ width: 1, height: 12, background: 'rgba(255,255,255,0.06)' }} />

          <button
            onClick={onToggleStreaming}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 12, color: streamingMode ? '#818cf8' : '#475569',
              padding: 0, transition: 'color 0.15s',
            }}
          >
            <Radio style={{ width: 12, height: 12, ...(streamingMode ? { animation: 'pulse 2s infinite' } : {}) }} />
            실시간 {streamingMode ? 'ON' : 'OFF'}
          </button>

          {!domainsLoading && domains.length > 0 && (
            <>
              <span style={{ width: 1, height: 12, background: 'rgba(255,255,255,0.06)' }} />
              <select
                value={selectedDomainId || ''}
                onChange={(e) => onDomainChange(e.target.value || null)}
                aria-label="검색 도메인 선택"
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  fontSize: 12, color: '#475569', outline: 'none', padding: 0,
                }}
              >
                <option value="">전체 도메인</option>
                {domains.map((d) => (
                  <option key={d.domain_id} value={d.domain_id}>{d.domain_name}</option>
                ))}
              </select>
            </>
          )}

          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: '#334155', display: 'flex', alignItems: 'center', gap: 4 }}>
            <Command style={{ width: 10, height: 10 }} /> Enter
          </span>
        </div>
      </motion.div>

      {/* 예제 쿼리 */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.3 }}
        style={{
          marginTop: 48, display: 'flex', flexWrap: 'wrap',
          justifyContent: 'center', gap: '6px 20px',
          position: 'relative', zIndex: 1,
        }}
      >
        {EXAMPLES.map((label) => (
          <button
            key={label}
            onClick={() => onSearch(label)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 13, color: '#475569', padding: '4px 0',
              transition: 'color 0.15s', display: 'flex', alignItems: 'center', gap: 4,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = '#94a3b8'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = '#475569'; }}
          >
            <ArrowRight style={{ width: 12, height: 12, opacity: 0.5 }} />
            {label}
          </button>
        ))}
      </motion.div>

      {/* 연결 경고 */}
      {!isConnected && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            marginTop: 32, display: 'flex', alignItems: 'center', gap: 8,
            padding: '10px 16px', borderRadius: 10,
            background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.12)',
            fontSize: 12, color: '#a16207', position: 'relative', zIndex: 1,
          }}
        >
          <WifiOff style={{ width: 14, height: 14 }} />
          법규 검색 서비스에 연결하지 못했습니다.
          <code style={{ background: 'rgba(251,191,36,0.1)', padding: '1px 5px', borderRadius: 4, fontSize: 11, fontFamily: 'monospace' }}>
            잠시 후 다시 확인해주세요.
          </code>
        </motion.div>
      )}
    </div>
  );
}
