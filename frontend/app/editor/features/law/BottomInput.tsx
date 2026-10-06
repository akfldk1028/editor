import { ArrowUp, Loader2, Search } from 'lucide-react'
import React from 'react'

import { glassInputHandlers } from './lib/glass-input'

// ─────────────────────────────────────────────────────────────────────────────
// BottomInput — 메시지 모드 하단 입력바
// ─────────────────────────────────────────────────────────────────────────────

export const BottomInput = React.memo(function BottomInput({
  query,
  onQueryChange,
  onKeyDown,
  onSearch,
  busy,
  inputRef,
}: {
  query: string
  onQueryChange: (v: string) => void
  onKeyDown: (e: React.KeyboardEvent) => void
  onSearch: () => void
  busy: boolean
  inputRef: React.RefObject<HTMLInputElement | null>
}) {
  return (
    <div
      style={{
        flexShrink: 0,
        borderTop: '1px solid rgba(255,255,255,0.06)',
        background: 'rgba(10,10,18,0.9)',
        backdropFilter: 'blur(16px)',
      }}
    >
      <div
        style={{
          maxWidth: 860,
          margin: '0 auto',
          padding: '12px 24px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center' }}>
          <Search
            style={{ position: 'absolute', left: 14, width: 18, height: 18, color: '#475569' }}
          />
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
              width: '100%',
              padding: '12px 48px 12px 42px',
              borderRadius: 16,
              border: '1px solid rgba(255,255,255,0.08)',
              background: 'rgba(255,255,255,0.04)',
              fontSize: 15,
              color: '#e2e8f0',
              outline: 'none',
              transition: 'all 0.2s',
              ...(busy ? { opacity: 0.5 } : {}),
            }}
            onFocus={glassInputHandlers.onFocus}
            onBlur={glassInputHandlers.onBlur}
          />
          <button
            onClick={onSearch}
            disabled={!query.trim() || busy}
            style={{
              position: 'absolute',
              right: 6,
              width: 34,
              height: 34,
              borderRadius: 12,
              border: 'none',
              cursor: query.trim() && !busy ? 'pointer' : 'default',
              background: query.trim() && !busy ? '#fff' : 'rgba(255,255,255,0.06)',
              color: query.trim() && !busy ? '#0a0a12' : '#475569',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s',
            }}
          >
            {busy ? (
              <Loader2 style={{ width: 16, height: 16, animation: 'spin 1s linear infinite' }} />
            ) : (
              <ArrowUp style={{ width: 16, height: 16 }} />
            )}
          </button>
        </div>
      </div>
    </div>
  )
})
