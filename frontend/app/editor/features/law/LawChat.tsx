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

import { AnimatePresence, motion } from 'framer-motion';
import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import AgentProgressPanel from '../land-map/components/AgentProgressPanel';
import { MapSearchBar } from '../land-map/components/MapSearchBar';
/* ── Components ── */
import { ArticleDetailPanel } from './components/ArticleDetailPanel';
import { BottomInput } from './components/BottomInput';
import { ChatHeader } from './components/ChatHeader';
import { HeroSearch } from './components/HeroSearch';
import { MapPanel } from './components/MapPanel';
import { MessageList } from './components/MessageList';
/* ── Context & hooks ── */
import { LawAPIProvider, useLawAPI } from './contexts/LawAPIContext';
import { useLawChat } from './hooks/use-law-chat';
import { useLawSearchStream } from './hooks/use-law-search-stream';
import type { AnalysisMode } from './hooks/use-map-law-search';
import { useMapLawSearch } from './hooks/use-map-law-search';
/* ── Types ── */
import type { LawArticle } from './lib/types';

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
// Export — LawAPIProvider 래핑
// ─────────────────────────────────────────────────────────────────────────────

export default function LawChat() {
  return (
    <LawAPIProvider>
      <LawChatInner />
    </LawAPIProvider>
  );
}
