/**
 * MapPanel — 3D Vworld 지도 패널 (로딩/에러/클릭토스트 오버레이 포함).
 *
 * LawChat 우측에 배치. useMapLawSearch 훅의 상태를 받아 오버레이만 렌더링.
 * 지도 자체는 외부에서 ref로 마운트 (useVworld3D가 직접 DOM 조작).
 */

import React from 'react';
import { Loader2 } from 'lucide-react';

/** MapPanel 자체 keyframes — 부모(LawChat) 의존 없이 독립 동작 */
const MAP_KEYFRAMES = `@keyframes spin { to { transform: rotate(360deg) } }`;

interface MapPanelProps {
  /** 맵 컨테이너 ref — useVworld3D 타겟 */
  mapRef: React.RefObject<HTMLDivElement | null>;
  /** 3D 맵 초기화 완료 */
  ready: boolean;
  /** 3D 맵 로딩 중 (스크립트/타일 로드) */
  loading: boolean;
  /** 3D 맵 에러 메시지 */
  error: string | null;
  /** 필지 클릭 → reverse geocode 진행 중 */
  clickLoading: boolean;
}

export function MapPanel({ mapRef, ready, loading, error, clickLoading }: MapPanelProps) {
  return (
    <div style={{
      flex: 1, position: 'relative', minWidth: 360,
      borderLeft: '1px solid rgba(255,255,255,0.06)',
    }}>
      <style>{MAP_KEYFRAMES}</style>
      {/* 지도 컨테이너 — useVworld3D가 직접 초기화 */}
      <div
        ref={mapRef}
        id="vworld-3d-map-law"
        style={{ width: '100%', height: '100%', background: '#0a0a1a' }}
      />

      {/* 필지 클릭 → 법규 검색 진행 토스트 (검색바 아래) */}
      {clickLoading && (
        <div style={{
          position: 'absolute', top: 72, left: '50%', transform: 'translateX(-50%)',
          zIndex: 20, padding: '8px 16px', borderRadius: 10,
          background: 'rgba(17,17,17,0.9)', backdropFilter: 'blur(12px)',
          border: '1px solid rgba(59,130,246,0.3)',
          display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 13, color: '#94a3b8',
        }}>
          <Loader2 style={{ width: 14, height: 14, animation: 'spin 1s linear infinite', color: '#3b82f6' }} />
          토지 분석 중...
        </div>
      )}

      {/* 초기 로딩 오버레이 */}
      {loading && !ready && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          zIndex: 10, background: 'rgba(10,10,26,0.85)',
          pointerEvents: 'none',
        }}>
          <svg width="40" height="40" viewBox="0 0 40 40"
            style={{ animation: 'spin 3s linear infinite', marginBottom: 12 }}>
            <circle cx="20" cy="20" r="16" fill="none" stroke="rgba(59,130,246,0.3)" strokeWidth="2" />
            <circle cx="20" cy="20" r="16" fill="none" stroke="#3b82f6" strokeWidth="2"
              strokeDasharray="80" strokeDashoffset="60" strokeLinecap="round" />
          </svg>
          <p style={{ fontSize: 13, color: '#94a3b8', fontWeight: 500 }}>3D 지도 로딩 중...</p>
          <p style={{ fontSize: 11, color: '#475569', marginTop: 3 }}>건물/지형 데이터를 불러오고 있습니다</p>
        </div>
      )}

      {/* 에러 패널 */}
      {error && (
        <div style={{
          position: 'absolute', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 15,
          background: 'rgba(17,17,17,0.92)', backdropFilter: 'blur(12px)',
          border: '1px solid rgba(239,68,68,0.2)',
          borderRadius: 12, padding: '16px 24px',
          textAlign: 'center', maxWidth: 300,
        }}>
          <p style={{ fontSize: 13, color: '#f87171', marginBottom: 4 }}>3D 지도 로드 실패</p>
          <p style={{ fontSize: 11, color: '#64748b' }}>{error}</p>
        </div>
      )}
    </div>
  );
}
