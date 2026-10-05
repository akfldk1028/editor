/**
 * 법규 검색 실시간 스트리밍 훅
 * SSE (Server-Sent Events)를 사용하여 검색 진행상황을 실시간 추적
 *
 * Backend endpoint: GET /law/search/stream?query=...&limit=...&domain_id=...
 * Django StreamingHttpResponse (text/event-stream) → Vite proxy → EventSource
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import type { LawArticle } from '../lib/types';

export type SearchProgressStatus = 'started' | 'searching' | 'processing' | 'complete' | 'error';

export type SearchStage =
  | 'exact_match'
  | 'vector_search'
  | 'relationship_search'
  | 'rne_expansion'
  | 'enrichment';

export interface SearchProgress {
  status: SearchProgressStatus;
  stage?: SearchStage;
  stage_name?: string;
  progress?: number;
  agent?: string;
  domain_id?: string;
  node_count?: number;
  timestamp?: number;
  results?: LawArticle[];
  result_count?: number;
  response_time?: number;
  domain_name?: string;
  message?: string;
}

export interface UseLawSearchStreamReturn {
  progress: SearchProgress | null;
  isSearching: boolean;
  startSearch: (query: string, limit?: number, domainId?: string) => void;
  stopSearch: () => void;
  resetProgress: () => void;
}

export function useLawSearchStream(
  baseURL: string = ''
): UseLawSearchStreamReturn {
  const [progress, setProgress] = useState<SearchProgress | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const cleanup = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const startSearch = useCallback(
    (query: string, limit: number = 10, domainId?: string) => {
      if (!query.trim()) return;

      cleanup();
      setIsSearching(true);
      setProgress({ status: 'started', progress: 0 });

      // Build SSE URL with query params
      const params = new URLSearchParams({
        query,
        limit: String(limit),
      });
      if (domainId) {
        params.set('domain_id', domainId);
      }
      const url = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/law/search/stream?${params.toString()}`;

      try {
        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        eventSource.onmessage = (event) => {
          try {
            const data: SearchProgress = JSON.parse(event.data);
            setProgress(data);

            if (data.status === 'complete' || data.status === 'error') {
              setIsSearching(false);
              cleanup();
            }
          } catch (error) {
            console.error('Failed to parse SSE data:', error);
          }
        };

        eventSource.onerror = () => {
          setProgress({
            status: 'error',
            message: '서버 연결에 실패했습니다. 서버 상태를 확인해주세요.',
          });
          setIsSearching(false);
          cleanup();
        };
      } catch (error) {
        setProgress({ status: 'error', message: 'EventSource 생성 실패' });
        setIsSearching(false);
      }
    },
    [baseURL, cleanup]
  );

  const stopSearch = useCallback(() => {
    cleanup();
    setIsSearching(false);
    setProgress((prev) => ({
      ...prev,
      status: 'error',
      message: '사용자가 검색을 중단했습니다.',
    } as SearchProgress));
  }, [cleanup]);

  const resetProgress = useCallback(() => {
    setProgress(null);
  }, []);

  useEffect(() => {
    return () => { cleanup(); };
  }, [cleanup]);

  return { progress, isSearching, startSearch, stopSearch, resetProgress };
}
