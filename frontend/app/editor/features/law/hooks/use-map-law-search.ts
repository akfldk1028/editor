/**
 * useMapLawSearch — 지적도 클릭/주소검색 → 토지 규제 분석 훅.
 *
 * 2D 지도(OpenLayers + Vworld Base 타일)와 토지 분석(/land/analyze/)을 연결.
 *
 * 클릭 흐름:
 *   OpenLayers singleclick → (lng, lat)
 *   → reverse()    — 좌표 → PNU + 주소 + geometry
 *   → highlightParcel(geometry)
 *   → analyze(pnu)  — PNU → 건폐율/용적률/41규제
 *   → addMessage(user: 주소) + addMessage(assistant: land_analysis)
 *
 * 주소 검색 흐름:
 *   MapSearchBar → searchByAddress(input)
 *   → resolve(input) — 주소 → PNU + 좌표
 *   → flyTo(좌표) + analyze(pnu)
 */

import { useRef, useEffect, useState, useCallback } from 'react';
import type { MapActions } from '../../world/components/MapEngine';
import { reverse, resolve, analyze, locateParcel } from '../../land-map/lib/land-api-client';
import { useAgentAnalyze } from '../../land-map/hooks/use-agent-analyze';
import type { ChatMessage } from '../lib/types';
import type { AgentAnalysisEvent, AgentMessage, LandAnalysisResult } from '../../land-map/lib/types';

export type AnalysisMode = 'quick' | 'agent';

interface UseMapLawSearchOptions {
  /** 검색/분석 중이면 클릭 무시 */
  busy: boolean;
  /** useLawChat.addMessage — 채팅에 메시지 추가 */
  addMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void;
}

interface UseMapLawSearchReturn {
  /** 3D 맵 초기화 완료 */
  mapReady: boolean;
  /** 3D 맵 로딩 중 */
  mapLoading: boolean;
  /** 3D 맵 에러 메시지 */
  mapError: string | null;
  /** 필지 클릭 → 분석 진행 중 */
  mapClickLoading: boolean;
  /** 분석 모드 ('quick' | 'agent') */
  analysisMode: AnalysisMode;
  /** 모드 토글 */
  setAnalysisMode: (mode: AnalysisMode) => void;
  /** 주소/PNU 검색 → 분석 */
  searchByAddress: (input: string) => Promise<void>;
  /** 3D 건물 표시/숨김 토글 */
  setBuildingsVisible: (visible: boolean) => void;
  /** 지도 엔진(MapEngine)이 자기 동작을 넘겨줄 때 */
  bindMap: (actions: MapActions) => void;
  /** 지도 클릭 → 필지 조회·분석 */
  onMapClick: (lng: number, lat: number) => void;
  /** 에이전트 분석 상태 (agent 모드용) */
  agent: {
    event: AgentAnalysisEvent | null;
    quickResult: LandAnalysisResult | null;
    messages: AgentMessage[];
    report: string | null;
    runSummary: { duration: number; total_tokens: number; turn_count: number } | null;
    progress: number;
    isRunning: boolean;
    stop: () => void;
  };
}

/**
 * 지적도 클릭/주소검색 → 토지 규제 분석.
 */
export function useMapLawSearch({
  busy,
  addMessage,
}: UseMapLawSearchOptions): UseMapLawSearchReturn {
  const [mapClickLoading, setMapClickLoading] = useState(false);
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>('quick');

  // ── Agent analysis SSE hook ──
  const {
    event: agentEvent,
    quickResult,
    agentMessages,
    report,
    runSummary,
    progress: agentProgress,
    isRunning: agentRunning,
    startAnalysis,
    stopAnalysis,
  } = useAgentAnalyze('');

  // ── Refs (순환 참조 방지) ──
  const highlightRef = useRef<(geojson: object) => void>(() => {});
  const clearHighlightRef = useRef<() => void>(() => {});
  const flyToRef = useRef<(lng: number, lat: number, zoom?: number) => void>(() => {});
  const drawSetbackRef = useRef<(lines: Record<string, unknown>) => void>(() => {});
  const clearSetbackRef = useRef<() => void>(() => {});
  const buildingsRef = useRef<(visible: boolean) => void>(() => {});
  const [mapState, setMapState] = useState<{ ready: boolean; loading: boolean; error: string | null }>({ ready: false, loading: true, error: null });
  const analyzingRef = useRef(false);
  const analysisModeRef = useRef(analysisMode);

  useEffect(() => { analysisModeRef.current = analysisMode; }, [analysisMode]);

  // ── Agent quick_done → addMessage + 규제선 렌더 (한 번만) ──
  const lastQuickResultRef = useRef<object | null>(null);
  useEffect(() => {
    if (quickResult && quickResult !== lastQuickResultRef.current) {
      lastQuickResultRef.current = quickResult;
      const pnu = quickResult.pnu;
      const addr = (typeof pnu === 'object' && pnu?.address) ? pnu.address : '';
      addMessage({
        role: 'assistant',
        content: addr || '토지 규제 분석 완료',
        land_analysis: quickResult,
      });
      // 규제선 3D 렌더
      if (quickResult.setback_lines) {
        drawSetbackRef.current(quickResult.setback_lines as Record<string, unknown>);
      }
    }
  }, [quickResult, addMessage]);

  /** 분석 공통 로직 (클릭/검색 공유) */
  const runAnalysis = useCallback(async (pnu: string, addr: string, geometry?: object) => {
    clearSetbackRef.current();
    if (geometry) highlightRef.current(geometry);
    addMessage({ role: 'user', content: addr });

    if (analysisModeRef.current === 'agent') {
      startAnalysis(pnu, addr);
      // agent 모드: quickResult effect에서 규제선 렌더
    } else {
      const result = await analyze(pnu, 'pnu');
      addMessage({ role: 'assistant', content: addr, land_analysis: result });
      // quick 모드: 즉시 규제선 렌더
      if (result.setback_lines) {
        drawSetbackRef.current(result.setback_lines as Record<string, unknown>);
      }
    }
  }, [addMessage, startAnalysis]);

  /** OpenLayers singleclick → reverse geocode → land analyze */
  const handleMapClick = useCallback(async (lng: number, lat: number) => {
    if (busy || analyzingRef.current) return;
    analyzingRef.current = true;
    setMapClickLoading(true);
    clearHighlightRef.current();

    try {
      const rev = await reverse(lng, lat);
      if (!rev.success || !rev.pnu) {
        addMessage({
          role: 'assistant',
          content: '이 위치의 필지 정보를 찾을 수 없습니다.',
          error: rev.error || '해당 좌표에 필지가 없습니다',
        });
        return;
      }
      await runAnalysis(rev.pnu, rev.address || rev.pnu, rev.geometry ?? undefined);
    } catch (e) {
      addMessage({
        role: 'assistant',
        content: '토지 분석 실패',
        error: e instanceof Error ? e.message : '알 수 없는 오류',
      });
    } finally {
      analyzingRef.current = false;
      setMapClickLoading(false);
    }
  }, [busy, addMessage, runAnalysis]);

  /**
   * 주소/PNU 검색.
   * - PNU 19자리: 바로 분석
   * - 번지 주소 ("문정동 123-4"): resolve → flyTo → 분석
   * - 동 단위 ("송파구 문정동"): flyTo만 (필지 클릭 대기)
   */
  const searchByAddress = useCallback(async (input: string) => {
    if (busy || analyzingRef.current) return;
    analyzingRef.current = true;
    setMapClickLoading(true);
    clearHighlightRef.current();

    try {
      const trimmed = input.trim();
      const isPnu = /^\d{19}$/.test(trimmed);

      if (isPnu) {
        // Fetch the parcel outline too, so the map shows the site and moves to it.
        const parcel = await locateParcel(trimmed).catch(() => null);
        await runAnalysis(trimmed, trimmed, parcel?.geometry);
        return;
      }

      // 번지 유무 판단: 끝에 숫자 또는 숫자-숫자 패턴 (예: 677, 123-4)
      const hasLotNumber = /\d+(-\d+)?$/.test(trimmed);

      const resolved = await resolve(trimmed, 'address');
      if (!resolved.success) {
        addMessage({
          role: 'assistant',
          content: '주소를 찾을 수 없습니다.',
          error: resolved.error || '주소 검색 실패',
        });
        return;
      }

      // 좌표가 있으면 지도 이동
      if (resolved.coordinates) {
        flyToRef.current(
          resolved.coordinates.x,
          resolved.coordinates.y,
          hasLotNumber ? 18 : 16, // 번지 → 가까이, 동 → 넓게
        );
      }

      // 번지가 있고 PNU도 확보 → 바로 분석
      if (hasLotNumber && resolved.pnu) {
        if (resolved.coordinates) {
          try {
            const rev = await reverse(resolved.coordinates.x, resolved.coordinates.y);
            if (rev.geometry) {
              await runAnalysis(resolved.pnu, resolved.address || trimmed, rev.geometry);
              return;
            }
          } catch { /* fallback */ }
        }
        // No coordinates (e.g. a PNU typed in): fetch the parcel outline so the map can show and reach it.
        const parcel = await locateParcel(resolved.pnu).catch(() => null);
        await runAnalysis(resolved.pnu, resolved.address || trimmed, parcel?.geometry);
      } else {
        // 동/구 단위 → 이동만, 클릭 대기 안내
        addMessage({
          role: 'assistant',
          content: `${resolved.geocoded_address || trimmed} 지역으로 이동했습니다. 지도에서 분석할 필지를 클릭하세요.`,
        });
      }
    } catch (e) {
      addMessage({
        role: 'assistant',
        content: '주소 검색 실패',
        error: e instanceof Error ? e.message : '알 수 없는 오류',
      });
    } finally {
      analyzingRef.current = false;
      setMapClickLoading(false);
    }
  }, [busy, addMessage, runAnalysis]);

  // ── 3D map: the engine (clean world or VWorld SDK) is mounted by MapEngine and hands its actions over here ──
  const bindMap = useCallback((a: MapActions) => {
    highlightRef.current = a.highlightParcel;
    clearHighlightRef.current = a.clearHighlight;
    flyToRef.current = a.flyTo;
    drawSetbackRef.current = a.drawSetbackLines;
    clearSetbackRef.current = a.clearSetbackLines;
    buildingsRef.current = a.setBuildingsVisible;
    setMapState((s) => (s.ready === a.ready && s.loading === a.loading && s.error === a.error ? s
      : { ready: a.ready, loading: a.loading, error: a.error }));
  }, []);
  const setBuildingsVisible = useCallback((visible: boolean) => buildingsRef.current(visible), []);
  const { ready: mapReady, loading: mapLoading, error: mapError } = mapState;

  return {
    mapReady, mapLoading, mapError, mapClickLoading,
    analysisMode, setAnalysisMode,
    searchByAddress, setBuildingsVisible, bindMap, onMapClick: handleMapClick,
    agent: {
      event: agentEvent,
      quickResult,
      messages: agentMessages,
      report,
      runSummary,
      progress: agentProgress,
      isRunning: agentRunning,
      stop: stopAnalysis,
    },
  };
}
