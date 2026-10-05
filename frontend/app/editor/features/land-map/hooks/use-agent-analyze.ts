/**
 * useAgentAnalyze — 에이전트 심화 분석 SSE 스트리밍 훅
 *
 * Backend: GET /land/agent-analyze/stream?pnu=...&address=...&zones=...
 *
 * Phase 1 (0-30%): 빠른 분석 → quick_done (규제 즉시 표시)
 * Phase 2 (30-95%): 6에이전트 협업 → agent 메시지 릴레이 → complete
 *
 * 패턴: use-law-search-stream.ts 동일 (EventSource + cleanup)
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import type {
  LandAnalysisResult,
  AgentAnalysisEvent,
  AgentMessage,
} from '../lib/types';

export interface UseAgentAnalyzeReturn {
  /** 현재 SSE 이벤트 (최신) */
  event: AgentAnalysisEvent | null;
  /** Phase 1 완료 시 규제 데이터 */
  quickResult: LandAnalysisResult | null;
  /** 에이전트 메시지 누적 (타임라인 표시용) */
  agentMessages: AgentMessage[];
  /** 최종 보고서 텍스트 */
  report: string | null;
  /** 실행 요약 */
  runSummary: { duration: number; total_tokens: number; turn_count: number } | null;
  /** 현재 진행률 (0–1) */
  progress: number;
  /** 분석 진행 중 */
  isRunning: boolean;
  /** 분석 시작 */
  startAnalysis: (pnu: string, address?: string, zones?: string[]) => void;
  /** 분석 중단 */
  stopAnalysis: () => void;
  /** 상태 초기화 */
  reset: () => void;
}

export function useAgentAnalyze(baseURL: string = ''): UseAgentAnalyzeReturn {
  const [event, setEvent] = useState<AgentAnalysisEvent | null>(null);
  const [quickResult, setQuickResult] = useState<LandAnalysisResult | null>(null);
  const [agentMessages, setAgentMessages] = useState<AgentMessage[]>([]);
  const [report, setReport] = useState<string | null>(null);
  const [runSummary, setRunSummary] = useState<UseAgentAnalyzeReturn['runSummary']>(null);
  const [progress, setProgress] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const cleanup = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    cleanup();
    setEvent(null);
    setQuickResult(null);
    setAgentMessages([]);
    setReport(null);
    setRunSummary(null);
    setProgress(0);
    setIsRunning(false);
  }, [cleanup]);

  const startAnalysis = useCallback(
    (pnu: string, address?: string, zones?: string[]) => {
      cleanup();
      setEvent(null);
      setQuickResult(null);
      setAgentMessages([]);
      setReport(null);
      setRunSummary(null);
      setProgress(0);
      setIsRunning(true);

      const params = new URLSearchParams();
      if (pnu) params.set('pnu', pnu);
      if (address) params.set('address', address);
      if (zones?.length) params.set('zones', zones.join(','));

      const url = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/agent-analyze/stream?${params.toString()}`;

      try {
        const es = new EventSource(url);
        eventSourceRef.current = es;

        es.onmessage = (ev) => {
          try {
            const data: AgentAnalysisEvent = JSON.parse(ev.data);
            setEvent(data);

            if ('progress' in data && typeof data.progress === 'number') {
              setProgress(data.progress);
            }

            switch (data.status) {
              case 'quick_done':
                setQuickResult(data.regulations);
                break;

              case 'agent':
                setAgentMessages(prev => [
                  ...prev,
                  {
                    agent: data.agent,
                    content: data.content,
                    turn: data.turn,
                    timestamp: Date.now(),
                  },
                ]);
                break;

              case 'complete':
                setReport(data.report);
                setRunSummary(data.run_summary);
                setProgress(1);
                setIsRunning(false);
                cleanup();
                break;

              case 'error':
                setIsRunning(false);
                cleanup();
                break;
            }
          } catch (err) {
            console.error('Failed to parse agent SSE data:', err);
          }
        };

        es.onerror = () => {
          setEvent({
            status: 'error',
            message: 'AI 심화 분석 서비스에 연결하지 못했습니다. 빠른 분석을 선택해 다시 시도해주세요.',
          });
          setIsRunning(false);
          cleanup();
        };
      } catch {
        setEvent({ status: 'error', message: 'EventSource 생성 실패' });
        setIsRunning(false);
      }
    },
    [baseURL, cleanup],
  );

  const stopAnalysis = useCallback(() => {
    cleanup();
    setIsRunning(false);
    setEvent({
      status: 'error',
      message: '사용자가 분석을 중단했습니다.',
    });
  }, [cleanup]);

  useEffect(() => {
    return () => { cleanup(); };
  }, [cleanup]);

  return {
    event, quickResult, agentMessages, report, runSummary,
    progress, isRunning, startAnalysis, stopAnalysis, reset,
  };
}
