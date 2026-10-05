import { useState, useCallback, useRef, useEffect } from 'react';
import type { SSEEvent, DesignData, GeoJSONFeature } from '../lib/types';
import { BASE, getJobResults, runJob } from '../lib/api-client';
import { persistedJobResult } from '../lib/persisted-job-result';

interface ObjectiveInfo {
  name: string;
  goal: string;
}

// Lightweight scatter point: [obj0, obj1, feasible, generation]
export type ScatterPoint = [number, number, boolean, number];

interface OptimizationStreamState {
  status: 'idle' | 'connecting' | 'running' | 'complete' | 'error' | 'cancelled';
  generation: number;
  maxGenerations: number;
  paretoFront: DesignData[];
  best: DesignData | null;
  bestGeojson: GeoJSONFeature | null;
  paretoGeojson: GeoJSONFeature[];
  feasibleCount: number;
  totalDesigns: number;
  error: string | null;
  progress: number; // 0-100
  objectives: ObjectiveInfo[];
  scatterHistory: ScatterPoint[]; // accumulated across generations
}

export function useOptimizationStream() {
  const [state, setState] = useState<OptimizationStreamState>({
    status: 'idle',
    generation: 0,
    maxGenerations: 0,
    paretoFront: [],
    best: null,
    bestGeojson: null,
    paretoGeojson: [],
    feasibleCount: 0,
    totalDesigns: 0,
    error: null,
    progress: 0,
    objectives: [],
    scatterHistory: [],
  });

  const scatterRef = useRef<ScatterPoint[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);
  const fallbackTimerRef = useRef<number | null>(null);
  const currentJobRef = useRef<string | null>(null);

  const clearFallbackTimer = useCallback(() => {
    if (fallbackTimerRef.current != null) {
      window.clearInterval(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
  }, []);

  const applyPersistedResults = useCallback((payload: any): boolean => {
    const result = persistedJobResult(payload);
    if (!result) return false;
    setState(prev => ({ ...prev, ...result }));
    return true;
  }, []);

  const fetchPersistedResults = useCallback(async (jobId: string) => {
    try {
      const payload = await getJobResults(jobId);
      if (currentJobRef.current !== jobId) return;
      if (applyPersistedResults(payload)) {
        clearFallbackTimer();
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
          eventSourceRef.current = null;
        }
      }
    } catch (error) {
      if ((process.env.NODE_ENV === 'development')) {
        console.warn('[Design][results-fallback] pending or failed', error);
      }
    }
  }, [applyPersistedResults, clearFallbackTimer]);

  const connect = useCallback((jobId: string) => {
    currentJobRef.current = jobId;
    // Close existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    clearFallbackTimer();

    // Reset scatter history from previous run (fixes stale color bug)
    scatterRef.current = [];

    setState(prev => ({
      ...prev,
      status: 'connecting',
      error: null,
      scatterHistory: [],
      paretoFront: [],
      paretoGeojson: [],
      best: null,
      bestGeojson: null,
      generation: 0,
      progress: 0,
      feasibleCount: 0,
      totalDesigns: 0,
    }));

    fallbackTimerRef.current = window.setInterval(() => {
      fetchPersistedResults(jobId);
    }, 1000);
    fetchPersistedResults(jobId);

    const usePollingOnly = (process.env.NODE_ENV === 'development')
      && new URLSearchParams(window.location.search).get('e2e') === '1';
    if (usePollingOnly) {
      setState(prev => ({
        ...prev,
        status: 'running',
        maxGenerations: prev.maxGenerations || 50,
      }));
      runJob(jobId)
        .catch((error) => {
          setState(prev => {
            if (prev.status === 'running' || prev.status === 'connecting') {
              return { ...prev, status: 'error', error: error instanceof Error ? error.message : 'Optimization stream failed' };
            }
            return prev;
          });
          clearFallbackTimer();
        });
      return;
    }

    const es = new EventSource(`${BASE}/jobs/${jobId}/stream`);
    eventSourceRef.current = es;

    const isCurrent = () => currentJobRef.current === jobId && eventSourceRef.current === es;

    es.addEventListener('started', (e) => {
      if (!isCurrent()) return;
      const data: SSEEvent = JSON.parse(e.data);
      setState(prev => ({
        ...prev,
        status: 'running',
        maxGenerations: data.max_generations || 0,
        objectives: data.objectives || [],
      }));
    });

    es.addEventListener('generation', (e) => {
      if (!isCurrent()) return;
      const data: SSEEvent = JSON.parse(e.data);
      const gen = data.generation || 0;
      // Accumulate scatter points across all generations
      if (data.scatter) {
        scatterRef.current = [...scatterRef.current, ...data.scatter];
      }
      setState(prev => {
        const maxGen = data.max_generations || prev.maxGenerations;
        return {
          ...prev,
          status: 'running',
          generation: gen,
          maxGenerations: maxGen,
          paretoFront: data.pareto_front || prev.paretoFront,
          best: data.best || prev.best,
          bestGeojson: data.best_geojson ?? prev.bestGeojson,
          paretoGeojson: data.pareto_geojson ?? prev.paretoGeojson,
          feasibleCount: data.feasible_count || 0,
          totalDesigns: data.total_evaluated || prev.totalDesigns,
          progress: maxGen > 0 ? Math.round((gen / maxGen) * 100) : 0,
          scatterHistory: scatterRef.current,
        };
      });
    });

    es.addEventListener('complete', (e) => {
      if (!isCurrent()) return;
      const data: SSEEvent = JSON.parse(e.data);
      clearFallbackTimer();
      setState(prev => ({
        ...prev,
        status: 'complete',
        paretoFront: data.pareto_front || prev.paretoFront,
        bestGeojson: data.best_geojson ?? prev.bestGeojson,
        paretoGeojson: data.pareto_geojson ?? prev.paretoGeojson,
        totalDesigns: data.total_designs || 0,
        generation: data.generations ?? prev.maxGenerations,
        progress: 100,
      }));
      es.close();
      eventSourceRef.current = null;
    });

    es.addEventListener('error', (e) => {
      if (!isCurrent()) return;
      // Transport errors have no data; EventSource reconnects using Last-Event-ID.
      // A named engine error carries data and is a terminal execution failure.
      if (!(e instanceof MessageEvent) || typeof e.data !== 'string') {
        if (es.readyState === EventSource.CONNECTING) {
          setState(prev => ({ ...prev, status: 'connecting' }));
        }
        return;
      }
      try {
        const data: SSEEvent = JSON.parse((e as MessageEvent).data);
        setState(prev => ({
          ...prev,
          status: 'error',
          error: data.message || 'Unknown error',
        }));
      } catch {
        setState(prev => ({
          ...prev,
          status: 'error',
          error: 'Connection lost',
        }));
      }
      es.close();
      eventSourceRef.current = null;
      clearFallbackTimer();
    });

    es.addEventListener('cancelled', () => {
      if (!isCurrent()) return;
      setState(prev => ({ ...prev, status: 'cancelled' }));
      es.close();
      eventSourceRef.current = null;
      clearFallbackTimer();
    });

    es.onerror = () => {
      if (!isCurrent()) return;
      // EventSource will auto-reconnect on transient errors
      // Only update state if the connection is truly closed
      if (es.readyState === EventSource.CLOSED) {
        setState(prev => {
          if (prev.status === 'running' || prev.status === 'connecting') {
            return { ...prev, status: 'error', error: 'Connection lost' };
          }
          return prev;
        });
      }
    };
  }, [clearFallbackTimer, fetchPersistedResults]);

  const disconnect = useCallback(() => {
    currentJobRef.current = null;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    clearFallbackTimer();
  }, [clearFallbackTimer]);

  useEffect(() => disconnect, [disconnect]);

  const reset = useCallback(() => {
    disconnect();
    scatterRef.current = [];
    setState({
      status: 'idle',
      generation: 0,
      maxGenerations: 0,
      paretoFront: [],
      best: null,
      bestGeojson: null,
      paretoGeojson: [],
      feasibleCount: 0,
      totalDesigns: 0,
      error: null,
      progress: 0,
      objectives: [],
      scatterHistory: [],
    });
  }, [disconnect]);

  return { ...state, connect, disconnect, reset, refresh: fetchPersistedResults };
}
