'use client'

import 'ol/ol.css';
/**
 * 토지 규제 분석 — Vworld 2D (OpenLayers) + 클릭 → PNU → 규제분석 → 시각화
 *
 * Route: /land
 */

import { useRef, useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

import { useVworldMap } from './hooks/use-vworld-map';
import { useLandAnalysis } from './hooks/use-land-analysis';
import { locateParcel } from './lib/land-api-client';
import { COLOR } from './lib/constants';
import { MapSearchBar } from './components/MapSearchBar';
import LandAnalysisPanel from './components/LandAnalysisPanel';

const KEYFRAMES = `
  @keyframes land-spin { to { transform: rotate(360deg) } }
  @keyframes land-shimmer {
    0% { background-position: -200% 0 }
    100% { background-position: 200% 0 }
  }
  @keyframes land-pulse {
    0%, 100% { opacity: 0.3 }
    50% { opacity: 0.6 }
  }
`;

export default function LandMap() {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const selection = useRef(0);
  const locationRequest = useRef<AbortController | null>(null);
  const [locationError, setLocationError] = useState<string | null>(null);
  useEffect(() => () => { selection.current++; locationRequest.current?.abort(); }, []);

  const {
    analysis, reverseResult, loading, error, step,
    analyzeByCoordinate, analyzeByInput,
  } = useLandAnalysis();

  const handleMapClick = useCallback(async (lng: number, lat: number) => {
    const selected = ++selection.current;
    locationRequest.current?.abort();
    setLocationError(null);
    clearHighlight();
    const result = await analyzeByCoordinate(lng, lat);
    if (selection.current === selected && result?.reverse?.geometry) {
      highlightParcel(result.reverse.geometry);
    }
  }, [analyzeByCoordinate]);

  const { mapError, highlightParcel, clearHighlight, drawSetbackLines, clearSetbackLines } = useVworldMap({
    target: mapContainerRef,
    onClick: handleMapClick,
  });

  // Draw setback lines when analysis result arrives
  useEffect(() => {
    if (analysis?.setback_lines) {
      drawSetbackLines(analysis.setback_lines);
    } else {
      clearSetbackLines();
    }
  }, [analysis, drawSetbackLines, clearSetbackLines]);

  const handleSearch = useCallback(async (input: string) => {
    const selected = ++selection.current;
    locationRequest.current?.abort();
    const controller = new AbortController();
    locationRequest.current = controller;
    setLocationError(null);
    clearHighlight();
    const analysisRequest = analyzeByInput(input);
    try {
      const parcel = await locateParcel(input, controller.signal);
      if (!controller.signal.aborted && selection.current === selected) {
        highlightParcel(parcel.geometry, true);
      }
    } catch (e) {
      if (!controller.signal.aborted && selection.current === selected) setLocationError(e instanceof Error ? e.message : '필지 위치를 확인하지 못했습니다.');
    }
    await analysisRequest;
  }, [analyzeByInput, clearHighlight, highlightParcel]);

  const displayAddress = reverseResult?.address
    || (analysis?.pnu && typeof analysis.pnu === 'object' ? (analysis.pnu as { address?: string }).address : null)
    || null;

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 56px)', background: COLOR.bg, color: COLOR.text }}>
      {/* 2D Map (OpenLayers) */}
      <div style={{ flex: 1, position: 'relative' }}>
        <div
          ref={mapContainerRef}
          style={{ width: '100%', height: '100%' }}
        />
        <MapSearchBar onSearch={handleSearch} loading={loading} />
        {mapError && <p role="alert" style={{ position: 'absolute', bottom: 12, left: 12, right: 12, padding: 12, background: COLOR.panelBg, color: COLOR.amber, zIndex: 20 }}>{mapError}</p>}
        <AnimatePresence>
          {loading && <LoadingOverlay step={step} />}
        </AnimatePresence>
      </div>

      {/* Analysis panel */}
      <div style={{
        width: 420, flexShrink: 0, overflowY: 'auto',
        background: COLOR.panelBg,
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderLeft: '1px solid rgba(255,255,255,0.05)',
        boxShadow: COLOR.panelShadow,
        padding: 20,
      }}>
        {locationError && <p role="alert" style={{ color: COLOR.amber, fontSize: 13, marginBottom: 12 }}>{locationError}</p>}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            style={{
              borderRadius: 10,
              background: 'rgba(239,68,68,0.06)',
              border: '1px solid rgba(239,68,68,0.12)',
              padding: '12px 14px', marginBottom: 12,
            }}
          >
            <p style={{ margin: 0, fontSize: 13, color: COLOR.red }}>{error}</p>
          </motion.div>
        )}

        <AnimatePresence mode="wait">
          {loading && !analysis ? (
            <SkeletonPanel key="skeleton" />
          ) : analysis ? (
            <LandAnalysisPanel key="result" analysis={analysis} address={displayAddress} />
          ) : (
            <EmptyState key="empty" />
          )}
        </AnimatePresence>
      </div>

      <style>{KEYFRAMES}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components (file-scoped, not exported)
// ---------------------------------------------------------------------------

function LoadingOverlay({ step }: { step: string | null }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 10 }}
      style={{
        position: 'absolute', bottom: 24, left: '50%', transform: 'translateX(-50%)',
        zIndex: 20,
        background: 'rgba(12,12,18,0.9)', backdropFilter: 'blur(16px)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 14, padding: '10px 22px',
        display: 'flex', alignItems: 'center', gap: 10,
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      }}
    >
      <div style={{
        width: 14, height: 14,
        border: '2px solid rgba(255,255,255,0.1)',
        borderTop: `2px solid ${COLOR.cyan}`,
        borderRadius: '50%',
        animation: 'land-spin 0.8s linear infinite',
      }} />
      <span style={{ fontSize: 13, color: COLOR.textSecondary }}>
        {step === 'reverse' ? '필지 조회 중...' : '규제 분석 중...'}
      </span>
    </motion.div>
  );
}

function SkeletonPanel() {
  const shimmerStyle = {
    background: 'linear-gradient(90deg, rgba(255,255,255,0.02) 25%, rgba(255,255,255,0.05) 50%, rgba(255,255,255,0.02) 75%)',
    backgroundSize: '200% 100%',
    animation: 'land-shimmer 1.5s ease-in-out infinite',
    borderRadius: 10,
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
    >
      <div>
        <div style={{ ...shimmerStyle, width: '70%', height: 16, marginBottom: 8 }} />
        <div style={{ ...shimmerStyle, width: '50%', height: 12 }} />
      </div>
      <div style={{ display: 'flex', gap: 10 }}>
        <div style={{ ...shimmerStyle, flex: 1, height: 96 }} />
        <div style={{ ...shimmerStyle, flex: 1, height: 96 }} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        <div style={{ ...shimmerStyle, width: '25%', height: 10, marginBottom: 4 }} />
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} style={{ ...shimmerStyle, height: 48 }} />
        ))}
      </div>
      <div style={{ ...shimmerStyle, height: 64 }} />
    </motion.div>
  );
}

function EmptyState() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, y: -8 }}
      style={{
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        height: '100%', gap: 12,
      }}
    >
      <div style={{
        width: 56, height: 56, borderRadius: 16,
        background: 'rgba(34,211,238,0.06)',
        border: '1px solid rgba(34,211,238,0.1)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        marginBottom: 4,
      }}>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={COLOR.cyan} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.7">
          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
      </div>
      <p style={{ margin: 0, fontSize: 15, fontWeight: 600, color: COLOR.textSecondary }}>
        필지를 선택하세요
      </p>
      <p style={{ margin: 0, fontSize: 13, color: COLOR.textDim, textAlign: 'center', lineHeight: 1.7 }}>
        지도에서 필지를 클릭하거나<br />
        주소를 검색하면<br />
        건폐율 · 용적률 · 건축제한 · 관련 법조항이<br />
        자동으로 분석됩니다
      </p>
    </motion.div>
  );
}
