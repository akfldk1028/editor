/**
 * Land analysis state hook — 좌표 또는 주소 → PNU → 규제 분석
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { reverse, analyze } from '../lib/land-api-client';
import { isPnu } from '../lib/constants';
import type { LandAnalysisResult, ReverseGeocodeResult } from '../lib/types';

interface AnalysisState {
  analysis: LandAnalysisResult | null;
  reverseResult: ReverseGeocodeResult | null;
  loading: boolean;
  error: string | null;
  step: 'reverse' | 'analyze' | null;
}

const INITIAL_STATE: AnalysisState = {
  analysis: null,
  reverseResult: null,
  loading: false,
  error: null,
  step: null,
};

export function useLandAnalysis() {
  const [state, setState] = useState<AnalysisState>(INITIAL_STATE);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  const begin = useCallback((step: 'reverse' | 'analyze') => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setState({ ...INITIAL_STATE, loading: true, step });
    return controller.signal;
  }, []);

  /** 좌표 클릭 → reverse geocode → analyze */
  const analyzeByCoordinate = useCallback(async (lng: number, lat: number) => {
    const signal = begin('reverse');

    try {
      const rev = await reverse(lng, lat, signal);
      if (signal.aborted) return { reverse: null, analysis: null };
      setState(prev => ({ ...prev, reverseResult: rev }));

      if (!rev.success || !rev.pnu) {
        setState(prev => ({
          ...prev,
          loading: false,
          error: rev.error || 'PNU를 찾을 수 없습니다',
          step: null,
        }));
        return { reverse: rev, analysis: null };
      }

      setState(prev => ({ ...prev, step: 'analyze' }));
      const result = await analyze(rev.pnu, 'pnu', undefined, rev.geometry, signal);
      if (signal.aborted) return { reverse: null, analysis: null };
      setState(prev => ({
        ...prev,
        analysis: result,
        loading: false,
        step: null,
      }));
      return { reverse: rev, analysis: result };
    } catch (e: unknown) {
      if (signal.aborted) return { reverse: null, analysis: null };
      const msg = e instanceof Error ? e.message : '분석 실패';
      setState(prev => ({ ...prev, loading: false, error: msg, step: null }));
      return { reverse: null, analysis: null };
    }
  }, [begin]);

  /** 주소/PNU 직접 입력 → analyze */
  const analyzeByInput = useCallback(async (input: string) => {
    const signal = begin('analyze');

    try {
      const inputType = isPnu(input) ? 'pnu' : 'address';
      const result = await analyze(input.trim(), inputType, undefined, undefined, signal);
      if (signal.aborted) return null;
      setState(prev => ({
        ...prev,
        analysis: result,
        loading: false,
        step: null,
      }));
      return result;
    } catch (e: unknown) {
      if (signal.aborted) return null;
      const msg = e instanceof Error ? e.message : '분석 실패';
      setState(prev => ({ ...prev, loading: false, error: msg, step: null }));
      return null;
    }
  }, [begin]);

  const clear = useCallback(() => {
    active.current?.abort();
    setState(INITIAL_STATE);
  }, []);

  return { ...state, analyzeByCoordinate, analyzeByInput, clear };
}
