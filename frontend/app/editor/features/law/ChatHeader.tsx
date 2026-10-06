import { Radio, RotateCcw, StopCircle, Wifi, WifiOff } from 'lucide-react'
import React from 'react'

import { Pill } from './components/Pill'

// ─────────────────────────────────────────────────────────────────────────────
// ChatHeader — 메시지 모드 상단 헤더
// ─────────────────────────────────────────────────────────────────────────────

export const ChatHeader = React.memo(function ChatHeader({
  isConnected,
  streamingMode,
  onToggleStreaming,
  domains,
  domainsLoading,
  selectedDomainId,
  onDomainChange,
  isSearching,
  onStopSearch,
  onClear,
}: {
  isConnected: boolean
  streamingMode: boolean
  onToggleStreaming: () => void
  domains: { domain_id: string; domain_name: string }[]
  domainsLoading: boolean
  selectedDomainId: string | null
  onDomainChange: (id: string | null) => void
  isSearching: boolean
  onStopSearch: () => void
  onClear: () => void
}) {
  return (
    <header
      style={{
        flexShrink: 0,
        padding: '10px 24px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        background: 'rgba(10,10,18,0.8)',
        backdropFilter: 'blur(16px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 600, color: '#64748b', letterSpacing: '-0.01em' }}>
        법규 검색
      </span>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Pill
          active={isConnected}
          activeColor="#34d399"
          activeBg="rgba(5,150,105,0.15)"
          inactiveColor="#f87171"
          inactiveBg="rgba(220,38,38,0.15)"
        >
          {isConnected ? (
            <Wifi style={{ width: 10, height: 10 }} />
          ) : (
            <WifiOff style={{ width: 10, height: 10 }} />
          )}
          {isConnected ? '연결' : '끊김'}
        </Pill>

        <Pill
          active={streamingMode}
          activeColor="#a5b4fc"
          activeBg="rgba(99,102,241,0.15)"
          inactiveColor="#64748b"
          inactiveBg="rgba(255,255,255,0.06)"
          onClick={onToggleStreaming}
          clickable
        >
          <Radio
            style={{
              width: 10,
              height: 10,
              ...(streamingMode ? { animation: 'pulse 2s infinite' } : {}),
            }}
          />
          실시간
        </Pill>

        {!domainsLoading && domains.length > 0 && (
          <select
            value={selectedDomainId || ''}
            onChange={(e) => onDomainChange(e.target.value || null)}
            aria-label="검색 도메인 선택"
            style={{
              padding: '4px 10px',
              borderRadius: 999,
              border: '1px solid rgba(255,255,255,0.08)',
              background: 'rgba(255,255,255,0.06)',
              fontSize: 10,
              fontWeight: 600,
              color: '#94a3b8',
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            <option value="">전체</option>
            {domains.map((d) => (
              <option key={d.domain_id} value={d.domain_id}>
                {d.domain_name}
              </option>
            ))}
          </select>
        )}

        {streamingMode && isSearching && (
          <Pill
            active
            activeColor="#f87171"
            activeBg="rgba(220,38,38,0.15)"
            onClick={onStopSearch}
            clickable
          >
            <StopCircle style={{ width: 10, height: 10 }} />
            중단
          </Pill>
        )}

        <Pill
          active={false}
          activeColor=""
          activeBg=""
          inactiveColor="#64748b"
          inactiveBg="rgba(255,255,255,0.06)"
          onClick={onClear}
          clickable
        >
          <RotateCcw style={{ width: 10, height: 10 }} />
          초기화
        </Pill>
      </div>
    </header>
  )
})
