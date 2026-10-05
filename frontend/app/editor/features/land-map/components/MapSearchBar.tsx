import React, { useState, useCallback } from 'react';
import { Search } from 'lucide-react';
import { COLOR } from '../lib/constants';

interface MapSearchBarProps {
  onSearch: (input: string) => void;
  loading?: boolean;
}

export const MapSearchBar = React.memo(function MapSearchBar({ onSearch, loading }: MapSearchBarProps) {
  const [value, setValue] = useState('');

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    onSearch(trimmed);
  }, [value, onSearch]);

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        position: 'absolute', top: 16, left: 16, right: 16, zIndex: 20,
        display: 'flex', gap: 8,
      }}
    >
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center',
        background: 'rgba(12,12,18,0.9)', backdropFilter: 'blur(16px)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 12, padding: '0 14px',
        boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
      }}>
        <Search style={{ width: 15, height: 15, color: COLOR.textDim, flexShrink: 0 }} />
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label="주소 또는 PNU 검색"
          placeholder="주소 또는 PNU 검색... (예: 강남구 역삼동 677)"
          style={{
            flex: 1, padding: '11px 10px',
            background: 'transparent', border: 'none',
            fontSize: 14, color: COLOR.text, outline: 'none',
          }}
        />
      </div>
      <button
        type="submit"
        disabled={loading || !value.trim()}
        style={{
          padding: '10px 22px', borderRadius: 12,
          background: loading ? 'rgba(255,255,255,0.05)' : 'rgba(34,211,238,0.12)',
          border: `1px solid ${loading ? 'rgba(255,255,255,0.06)' : 'rgba(34,211,238,0.2)'}`,
          color: loading ? COLOR.textMuted : COLOR.text,
          fontSize: 13, fontWeight: 600, cursor: loading ? 'wait' : 'pointer',
          opacity: !value.trim() ? 0.4 : 1,
          transition: 'all 0.15s',
          boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
          backdropFilter: 'blur(16px)',
        }}
      >
        {loading ? '분석중...' : '검색'}
      </button>
    </form>
  );
});
