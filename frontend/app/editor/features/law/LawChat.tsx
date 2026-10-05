'use client'

/**
 * LawChat — 법규 AI 검색 페이지 (조합 컴포넌트).
 *
 * 3패널 레이아웃: [Chat(좌)] | [3D Map(우)] | [ArticleDetail(사이드바)]
 *
 * 책임 분리:
 *   - HeroSearch: 빈 상태 검색 UI (Perplexity 스타일)
 *   - MapPanel: 3D Vworld 지도 + 오버레이
 *   - useMapLawSearch: 지적도 클릭 → reverse geocode → 법규 검색
 *   - Pill: 상태 배지 컴포넌트
 *   - useLawChat: 채팅 메시지 + 검색 API
 *   - useLawSearchStream: SSE 실시간 검색
 *
 * 스타일: inline hex (Tailwind CSS 변수 충돌 회피)
 */

import React, { useRef, useEffect, useState } from 'react';
import {
  Wifi,
  WifiOff,
  Radio,
  RotateCcw,
  StopCircle,
  Search,
  Loader2,
  ArrowUp,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

/* ── Context & hooks ── */
import { LawAPIProvider, useLawAPI } from './contexts/LawAPIContext';
import { useLawChat } from './hooks/use-law-chat';
import { useLawSearchStream } from './hooks/use-law-search-stream';
import { useMapLawSearch } from './hooks/use-map-law-search';

/* ── Components ── */
import { ResultDisplay } from './components/ResultDisplay';
import { ArticleDetailPanel } from './components/ArticleDetailPanel';
import { SearchProgressIndicator, SearchCompleteHeader, SearchErrorIndicator } from './components/SearchProgress';
import { HeroSearch } from './components/HeroSearch';
import { MapPanel } from './components/MapPanel';
import { Pill } from './components/Pill';
import { MapSearchBar } from '../land-map/components/MapSearchBar';
import LandAnalysisPanel from '../land-map/components/LandAnalysisPanel';
import AgentProgressPanel from '../land-map/components/AgentProgressPanel';

/* ── Types ── */
import type { LawArticle, ChatMessage } from './lib/types';
import type { SearchProgress } from './hooks/use-law-search-stream';
import type { AnalysisMode } from './hooks/use-map-law-search';
import { glassInputHandlers } from './lib/glass-input';

/* ── Constants ── */
const ANALYSIS_MODES = [['quick', '빠른 분석'], ['agent', 'AI 심화 분석']] as const;

/* ── Global keyframes (map + chat 공용) ── */
const KEYFRAMES = `
  @keyframes spin { to { transform: rotate(360deg) } }
  @keyframes pulse { 0%, 100% { opacity: 1 } 50% { opacity: 0.5 } }
  @keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }
  @keyframes borderBeam { 0% { left: -20%; } 100% { left: 120%; } }
  @keyframes fillRing { from { stroke-dashoffset: 88; } to { stroke-dashoffset: 0; } }
  @keyframes matchGlow {
    0%, 100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.05); }
    50% { box-shadow: 0 0 20px 4px rgba(99,102,241,0.1); }
  }
`;

// ─────────────────────────────────────────────────────────────────────────────
// LawChatInner — 메인 조합 컴포넌트
// ─────────────────────────────────────────────────────────────────────────────

function LawChatInner() {
  /* ── API context ── */
  const { domains, domainsLoading, selectedDomainId, setSelectedDomainId, isConnected } =
    useLawAPI();

  /* ── Chat state ── */
  const { messages, isLoading, search, clearMessages, addMessage } = useLawChat();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  /* ── SSE streaming ── */
  const { progress, isSearching, startSearch, stopSearch, resetProgress } =
    useLawSearchStream('');

  /* ── Local state ── */
  const [streamingMode, setStreamingMode] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedArticle, setSelectedArticle] = useState<LawArticle | null>(null);

  /* ── Derived ── */
  const busy = isLoading || isSearching;
  const hasMessages = messages.length > 0;

  /* ── 3D Map (다이어그램) + 지적도 클릭/검색→법규 분석 ── */
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const { mapReady, mapLoading, mapError, mapClickLoading, analysisMode, setAnalysisMode, searchByAddress, setBuildingsVisible, agent } =
    useMapLawSearch({ target: mapContainerRef, busy, addMessage });
  const [buildingsOn, setBuildingsOn] = useState(true);
  useEffect(() => {
    if (mapReady) setBuildingsVisible(buildingsOn);
  }, [mapReady, buildingsOn, setBuildingsVisible]);

  /* ── 메시지 자동 스크롤 ── */
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  /* ── SSE 완료 시 결과를 채팅에 추가 ── */
  useEffect(() => {
    if (progress?.status === 'complete' && progress.results) {
      addMessage({
        role: 'assistant',
        content: `검색 완료 (${progress.response_time ?? 0}ms)`,
        search_response: {
          results: progress.results,
          total_count: progress.result_count || progress.results.length,
          query: '',
          response_time: progress.response_time || 0,
          domain_id: progress.domain_id,
          domain_name: progress.domain_name,
        },
      });
      resetProgress();
    }
  }, [progress, addMessage, resetProgress]);

  /* ── 검색 실행 (텍스트 입력/예제 클릭) ── */
  const handleSearch = (q: string) => {
    const trimmed = q.trim();
    if (!trimmed || busy) return;
    setQuery('');
    if (streamingMode) {
      addMessage({ role: 'user', content: trimmed });
      resetProgress();
      startSearch(trimmed, 10, selectedDomainId || undefined);
    } else {
      search(trimmed, 10);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSearch(query);
    }
  };

  // ───────────────────────────────────────────────────────────────────────────
  // Render
  // ───────────────────────────────────────────────────────────────────────────

  return (
    <div style={{
      display: 'flex', height: 'calc(100vh - 56px)',
      background: '#0a0a12',
      position: 'relative', overflow: 'hidden',
    }}>
      {/* Ambient gradient mesh (subtle background atmosphere) */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 60% 50% at 20% 50%, rgba(59,130,246,0.04) 0%, transparent 70%), radial-gradient(ellipse 50% 60% at 80% 30%, rgba(139,92,246,0.03) 0%, transparent 70%)',
      }} />
      <style>{KEYFRAMES}</style>

      {/* ═══ Left: Chat Panel ═══ */}
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 400, position: 'relative', zIndex: 1 }}>

        {/* 헤더 (메시지 있을 때만) */}
        {hasMessages && (
          <ChatHeader
            isConnected={isConnected}
            streamingMode={streamingMode}
            onToggleStreaming={() => setStreamingMode(prev => !prev)}
            domains={domains}
            domainsLoading={domainsLoading}
            selectedDomainId={selectedDomainId}
            onDomainChange={setSelectedDomainId}
            isSearching={isSearching}
            onStopSearch={stopSearch}
            onClear={clearMessages}
          />
        )}

        {/* 콘텐츠: 히어로 or 메시지 */}
        {hasMessages ? (
          <MessageList
            messages={messages}
            streamingMode={streamingMode}
            isSearching={isSearching}
            progress={progress}
            selectedArticle={selectedArticle}
            onSelectArticle={setSelectedArticle}
            messagesEndRef={messagesEndRef}
          />
        ) : (
          <HeroSearch
            query={query}
            onQueryChange={setQuery}
            onSearch={handleSearch}
            busy={busy}
            isConnected={isConnected}
            streamingMode={streamingMode}
            onToggleStreaming={() => setStreamingMode(prev => !prev)}
            domains={domains}
            domainsLoading={domainsLoading}
            selectedDomainId={selectedDomainId}
            onDomainChange={setSelectedDomainId}
            inputRef={inputRef}
          />
        )}

        {/* 하단 입력바 (메시지 모드) */}
        {hasMessages && (
          <BottomInput
            query={query}
            onQueryChange={setQuery}
            onKeyDown={handleKeyDown}
            onSearch={() => handleSearch(query)}
            busy={busy}
            inputRef={inputRef}
          />
        )}
      </div>

      {/* ═══ Right: 3D Map (다이어그램) + Search + Agent Panel ═══ */}
      <div style={{
        display: 'flex', flexDirection: 'column', flex: 1, minWidth: 360, position: 'relative', zIndex: 1,
        borderLeft: '1px solid rgba(255,255,255,0.04)',
      }}>
        {/* 주소 검색창 (MapPanel 내부 relative 컨테이너 기준) */}
        <MapSearchBar onSearch={searchByAddress} loading={mapClickLoading || agent.isRunning} />

        {/* Mode toggle + 건물 토글 — 검색바 아래 */}
        <div style={{
          position: 'absolute', top: 64, left: 16, zIndex: 10,
          display: 'flex', gap: 6, alignItems: 'center',
        }}>
          <div style={{
            display: 'flex', gap: 4, padding: 3,
            background: 'rgba(0,0,0,0.6)', borderRadius: 8,
            backdropFilter: 'blur(8px)',
          }}>
            {ANALYSIS_MODES.map(([mode, label]) => (
              <button
                key={mode}
                onClick={() => setAnalysisMode(mode)}
                style={{
                  padding: '5px 12px', borderRadius: 6, border: 'none',
                  fontSize: 12, fontWeight: 500, cursor: 'pointer',
                  transition: 'all 0.2s',
                  background: analysisMode === mode ? 'rgba(99,102,241,0.8)' : 'transparent',
                  color: analysisMode === mode ? '#fff' : '#94a3b8',
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            onClick={() => {
              const next = !buildingsOn;
              setBuildingsOn(next);
            }}
            style={{
              padding: '5px 12px', borderRadius: 8, border: 'none',
              fontSize: 12, fontWeight: 500, cursor: 'pointer',
              background: buildingsOn ? 'rgba(0,0,0,0.6)' : 'rgba(239,68,68,0.3)',
              color: buildingsOn ? '#94a3b8' : '#fca5a5',
              backdropFilter: 'blur(8px)',
              transition: 'all 0.2s',
            }}
          >
            {buildingsOn ? '🏢 건물 ON' : '🏢 건물 OFF'}
          </button>
        </div>

        <MapPanel
          mapRef={mapContainerRef}
          ready={mapReady}
          loading={mapLoading}
          error={mapError}
          clickLoading={mapClickLoading || agent.isRunning}
        />

        {/* Agent progress overlay (bottom of map) */}
        {analysisMode === 'agent' && (agent.event || agent.isRunning || agent.messages.length > 0 || agent.report) && (
          <div style={{
            position: 'absolute', bottom: 0, left: 0, right: 0,
            maxHeight: '50%', overflowY: 'auto',
            padding: '0 12px 12px',
          }}>
            <AgentProgressPanel
              messages={agent.messages}
              event={agent.event}
              progress={agent.progress}
              isRunning={agent.isRunning}
              report={agent.report}
              runSummary={agent.runSummary}
              onStop={agent.stop}
            />
          </div>
        )}
      </div>

      {/* ═══ Sidebar: Article Detail (animated) ═══ */}
      <AnimatePresence>
        {selectedArticle && (
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: 420 }}
            exit={{ width: 0 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
            style={{ flexShrink: 0, overflow: 'hidden', height: 'calc(100vh - 56px)' }}
          >
            <div style={{ width: 420, height: '100%' }}>
              <ArticleDetailPanel
                article={selectedArticle}
                onClose={() => setSelectedArticle(null)}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ChatHeader — 메시지 모드 상단 헤더
// ─────────────────────────────────────────────────────────────────────────────

const ChatHeader = React.memo(function ChatHeader({
  isConnected, streamingMode, onToggleStreaming,
  domains, domainsLoading, selectedDomainId, onDomainChange,
  isSearching, onStopSearch, onClear,
}: {
  isConnected: boolean;
  streamingMode: boolean;
  onToggleStreaming: () => void;
  domains: { domain_id: string; domain_name: string }[];
  domainsLoading: boolean;
  selectedDomainId: string | null;
  onDomainChange: (id: string | null) => void;
  isSearching: boolean;
  onStopSearch: () => void;
  onClear: () => void;
}) {
  return (
    <header style={{
      flexShrink: 0, padding: '10px 24px',
      borderBottom: '1px solid rgba(255,255,255,0.06)',
      background: 'rgba(10,10,18,0.8)', backdropFilter: 'blur(16px)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: '#64748b', letterSpacing: '-0.01em' }}>
        법규 검색
      </span>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Pill
          active={isConnected}
          activeColor="#34d399" activeBg="rgba(5,150,105,0.15)"
          inactiveColor="#f87171" inactiveBg="rgba(220,38,38,0.15)"
        >
          {isConnected
            ? <Wifi style={{ width: 10, height: 10 }} />
            : <WifiOff style={{ width: 10, height: 10 }} />
          }
          {isConnected ? '연결' : '끊김'}
        </Pill>

        <Pill
          active={streamingMode}
          activeColor="#a5b4fc" activeBg="rgba(99,102,241,0.15)"
          inactiveColor="#64748b" inactiveBg="rgba(255,255,255,0.06)"
          onClick={onToggleStreaming}
          clickable
        >
          <Radio style={{ width: 10, height: 10, ...(streamingMode ? { animation: 'pulse 2s infinite' } : {}) }} />
          실시간
        </Pill>

        {!domainsLoading && domains.length > 0 && (
          <select
            value={selectedDomainId || ''}
            onChange={(e) => onDomainChange(e.target.value || null)}
            aria-label="검색 도메인 선택"
            style={{
              padding: '4px 10px', borderRadius: 999,
              border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.06)',
              fontSize: 10, fontWeight: 600, color: '#94a3b8',
              outline: 'none', cursor: 'pointer',
            }}
          >
            <option value="">전체</option>
            {domains.map((d) => (
              <option key={d.domain_id} value={d.domain_id}>{d.domain_name}</option>
            ))}
          </select>
        )}

        {streamingMode && isSearching && (
          <Pill active activeColor="#f87171" activeBg="rgba(220,38,38,0.15)" onClick={onStopSearch} clickable>
            <StopCircle style={{ width: 10, height: 10 }} />
            중단
          </Pill>
        )}

        <Pill active={false} activeColor="" activeBg="" inactiveColor="#64748b" inactiveBg="rgba(255,255,255,0.06)" onClick={onClear} clickable>
          <RotateCcw style={{ width: 10, height: 10 }} />
          초기화
        </Pill>
      </div>
    </header>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// MessageList — 채팅 메시지 목록 + SSE 진행률
// ─────────────────────────────────────────────────────────────────────────────

const MessageList = React.memo(function MessageList({
  messages, streamingMode, isSearching, progress,
  selectedArticle, onSelectArticle, messagesEndRef,
}: {
  messages: ChatMessage[];
  streamingMode: boolean;
  isSearching: boolean;
  progress: SearchProgress | null;
  selectedArticle: LawArticle | null;
  onSelectArticle: (a: LawArticle | null) => void;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div style={{ flex: 1, overflowY: 'auto' }}>
      <div style={{ maxWidth: 860, margin: '0 auto', padding: '24px 24px 32px' }}>
        <AnimatePresence mode="popLayout">
          {messages.map((message) => (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.25 }}
              style={{ marginBottom: 20 }}
            >
              {message.role === 'user' && (
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <div style={{
                    maxWidth: '70%', padding: '10px 16px', borderRadius: 12,
                    background: 'rgba(99,102,241,0.12)',
                    border: '1px solid rgba(99,102,241,0.15)',
                    color: '#e2e8f0', fontSize: 14, fontWeight: 500,
                  }}>
                    {message.content}
                  </div>
                </div>
              )}
              {message.role === 'assistant' && (
                <div style={{ width: '100%' }}>
                  {message.loading && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 0' }}>
                      {[0, 1, 2].map((i) => (
                        <div key={i} style={{
                          height: i === 0 ? 16 : 12,
                          width: i === 2 ? '60%' : '100%',
                          borderRadius: 4,
                          background: 'linear-gradient(90deg, rgba(255,255,255,0.02) 25%, rgba(255,255,255,0.05) 50%, rgba(255,255,255,0.02) 75%)',
                          backgroundSize: '200% 100%',
                          animation: 'shimmer 1.5s linear infinite',
                          animationDelay: `${i * 0.1}s`,
                        }} />
                      ))}
                      <span style={{ fontSize: 12, color: '#334155', marginTop: 4 }}>{message.content}</span>
                    </div>
                  )}
                  {message.error && !message.loading && (
                    <SearchErrorIndicator message={message.error} />
                  )}
                  {message.land_analysis && !message.loading && !message.error && (
                    <LandAnalysisPanel
                      analysis={message.land_analysis}
                      address={message.content}
                      onSelectArticle={(a) => onSelectArticle({
                        hang_id: a.hang_id,
                        content: a.content,
                        similarity: a.similarity || 0,
                        stages: a.stages || [],
                        source: 'land',
                        law_name: a.law_name,
                        law_type: a.law_type,
                        article: a.article,
                      })}
                    />
                  )}
                  {message.search_response && !message.loading && !message.error && (
                    <div>
                      <div style={{ marginBottom: 8 }}>
                        <SearchCompleteHeader
                          resultCount={message.search_response.total_count || message.search_response.results.length}
                          responseTime={message.search_response.response_time || 0}
                          domainName={message.search_response.domain_name}
                        />
                      </div>
                      <ResultDisplay
                        response={message.search_response}
                        selectedArticle={selectedArticle}
                        onSelectArticle={onSelectArticle}
                      />
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {/* SSE 스트리밍 진행률 */}
        {streamingMode && isSearching && progress && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            style={{
              padding: 20, borderRadius: 20,
              background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
            }}
          >
            {progress.status !== 'complete' && progress.status !== 'error' && (
              <SearchProgressIndicator progress={progress} />
            )}
            {progress.status === 'error' && (
              <SearchErrorIndicator message={progress.message || '알 수 없는 오류'} />
            )}
            {progress.status === 'complete' && (
              <SearchCompleteHeader
                resultCount={progress.result_count || 0}
                responseTime={progress.response_time || 0}
                domainName={progress.domain_name}
              />
            )}
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>
    </div>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// BottomInput — 메시지 모드 하단 입력바
// ─────────────────────────────────────────────────────────────────────────────

const BottomInput = React.memo(function BottomInput({
  query, onQueryChange, onKeyDown, onSearch, busy, inputRef,
}: {
  query: string;
  onQueryChange: (v: string) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onSearch: () => void;
  busy: boolean;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  return (
    <div style={{
      flexShrink: 0, borderTop: '1px solid rgba(255,255,255,0.06)',
      background: 'rgba(10,10,18,0.9)', backdropFilter: 'blur(16px)',
    }}>
      <div style={{
        maxWidth: 860, margin: '0 auto', padding: '12px 24px',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center' }}>
          <Search style={{ position: 'absolute', left: 14, width: 18, height: 18, color: '#475569' }} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="법규 내용을 검색하세요..."
            disabled={busy}
            aria-label="법규 검색어 입력"
            style={{
              width: '100%', padding: '12px 48px 12px 42px',
              borderRadius: 16, border: '1px solid rgba(255,255,255,0.08)',
              background: 'rgba(255,255,255,0.04)', fontSize: 15, color: '#e2e8f0',
              outline: 'none', transition: 'all 0.2s',
              ...(busy ? { opacity: 0.5 } : {}),
            }}
            onFocus={glassInputHandlers.onFocus}
            onBlur={glassInputHandlers.onBlur}
          />
          <button
            onClick={onSearch}
            disabled={!query.trim() || busy}
            style={{
              position: 'absolute', right: 6, width: 34, height: 34,
              borderRadius: 12, border: 'none',
              cursor: query.trim() && !busy ? 'pointer' : 'default',
              background: query.trim() && !busy ? '#fff' : 'rgba(255,255,255,0.06)',
              color: query.trim() && !busy ? '#0a0a12' : '#475569',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'all 0.2s',
            }}
          >
            {busy
              ? <Loader2 style={{ width: 16, height: 16, animation: 'spin 1s linear infinite' }} />
              : <ArrowUp style={{ width: 16, height: 16 }} />
            }
          </button>
        </div>
      </div>
    </div>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Export — LawAPIProvider 래핑
// ─────────────────────────────────────────────────────────────────────────────

export default function LawChat() {
  return (
    <LawAPIProvider>
      <LawChatInner />
    </LawAPIProvider>
  );
}
