import { useEffect, useRef, useState } from 'react';
import { getAgLightBusLog, getAgLightHealth, getDesignEvidence, sendAgLightBusMessage, type AgLightBusEvent, type AgLightHealth } from '../lib/api-client';
import { buildAgentTrace, getMassLegalStatus, makeAgentReviews, type AgentTrace } from '../lib/ag-light-collaboration';
import type { AGLightReview } from '../components/ag-light-flow/types';
import type { InteractiveDesignProps } from './use-interactive-design';

type AgentReviewInput = Pick<InteractiveDesignProps, 'jobId' | 'design' | 'massGeojson' | 'setbackGeometries' | 'buildingType' | 'algorithm' | 'onAestheticGenerated' | 'onPreviewCandidate'>;

export function useInteractiveAgentReview({ jobId, design, massGeojson, setbackGeometries, buildingType, algorithm }: AgentReviewInput) {
  const [agHealth, setAgHealth] = useState<AgLightHealth | null>(null);
  const [agBusLog, setAgBusLog] = useState<AgLightBusEvent[]>([]);
  const [agReviews, setAgReviews] = useState<AGLightReview[]>([]);
  const [agTrace, setAgTrace] = useState<AgentTrace[]>([]);
  const [agLoading, setAgLoading] = useState(false);
  const [agError, setAgError] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState('law_graph_agent');
  const identity = JSON.stringify([jobId, design.id, design.uid, design.algorithm,
    massGeojson?.properties?.design_id, massGeojson?.properties?.design_uid]);
  const identityRef = useRef(identity);
  identityRef.current = identity;
  const activeRef = useRef(true);
  const reviewRequestRef = useRef(0);
  const directRequestRef = useRef(0);

  useEffect(() => {
    activeRef.current = true;
    setAgReviews([]);
    setAgTrace([]);
    setAgError('');
    setAgLoading(false);
    setAgHealth(null);
    setAgBusLog([]);
    return () => {
      activeRef.current = false;
      reviewRequestRef.current += 1;
      directRequestRef.current += 1;
    };
  }, [identity]);

  useEffect(() => {
    let cancelled = false;
    const refreshAgLight = async () => {
      try {
        const [health, log] = await Promise.all([
          getAgLightHealth(),
          getAgLightBusLog(20),
        ]);
        if (!cancelled && activeRef.current && identityRef.current === identity) {
          setAgHealth(health);
          setAgBusLog(log);
          setAgError('');
        }
      } catch (e) {
        if (!cancelled && activeRef.current && identityRef.current === identity) {
          setAgError(e instanceof Error ? e.message : 'AG-light 연결 실패');
        }
      }
    };
    refreshAgLight();
    return () => {
      cancelled = true;
    };
  }, [identity]);

  const runAgLightReview = async () => {
    if (!activeRef.current || identityRef.current !== identity) return;
    if (!jobId) {
      setAgError('저장된 최적화 job이 있어야 AG-light 검토를 실행할 수 있습니다.');
      return;
    }
    const rawDesignId = massGeojson?.properties?.design_id;
    const evidenceDesignId = typeof rawDesignId === 'number' ? rawDesignId : design.id;
    const request = ++reviewRequestRef.current;
    const ownsReview = () => activeRef.current && identityRef.current === identity
      && reviewRequestRef.current === request;
    setAgLoading(true);
    setAgError('');
    try {
      const evidence = await getDesignEvidence(jobId, evidenceDesignId);
      if (!ownsReview()) return;
      const reviews = makeAgentReviews(evidence, massGeojson, setbackGeometries);
      const trace = buildAgentTrace(reviews, evidence, massGeojson, setbackGeometries);
      const metadata = {
        job_id: jobId,
        design_id: evidenceDesignId,
        design_uid: design.uid || massGeojson?.properties?.design_uid,
        source: 'arr_design_ui',
        final_status: getMassLegalStatus(evidence, massGeojson),
      };
      const handoffTargets: Record<string, string> = {
        law_graph_agent: 'parking_agent',
        parking_agent: 'maas_geometry_agent',
        maas_geometry_agent: 'review_agent',
        review_agent: 'design_orchestrator',
      };
      for (const review of reviews) {
        // A prior handoff may settle after the user changes the selected job.
        if (!ownsReview()) return;
        const agentTrace = trace.find((item) => item.agent === review.agent);
        await sendAgLightBusMessage({
          from_agent: review.agent,
          to_agent: handoffTargets[review.agent] || 'design_orchestrator',
          event_type: 'agent_reasoning_handoff',
          message: `${review.label}: ${review.summary} · 공식 ${agentTrace?.formula || 'n/a'} · 근거 ${agentTrace?.refs.join(', ') || 'none'} · 판단 ${agentTrace?.decision || review.detail}`,
          metadata: {
            ...metadata,
            status: review.status,
            label: review.label,
            refs: agentTrace?.refs || [],
            formula: agentTrace?.formula,
            decision: agentTrace?.decision,
          },
        });
      }
      if (!ownsReview()) return;
      setAgReviews(reviews);
      setAgTrace(trace);
      const [health, log] = await Promise.all([
        getAgLightHealth(),
        getAgLightBusLog(40),
      ]);
      if (!ownsReview()) return;
      setAgHealth(health);
      setAgBusLog(log);
    } catch (e) {
      if (!ownsReview()) return;
      const fallbackReviews = makeAgentReviews(null, massGeojson, setbackGeometries);
      const fallbackTrace = buildAgentTrace(fallbackReviews, null, massGeojson, setbackGeometries);
      setAgReviews(fallbackReviews);
      setAgTrace(fallbackTrace);
      setAgError(e instanceof Error ? e.message : 'AG-light 검토 실패');
    } finally {
      if (ownsReview()) setAgLoading(false);
    }
  };

  const sendDirectAgentMessage = async (targetAgent: string, directMessage: string) => {
    if (!activeRef.current || identityRef.current !== identity) return;
    const request = ++directRequestRef.current;
    const ownsMessage = () => activeRef.current && identityRef.current === identity
      && directRequestRef.current === request;
    const rawDesignId = massGeojson?.properties?.design_id;
    const evidenceDesignId = typeof rawDesignId === 'number' ? rawDesignId : design.id;
    try {
      await sendAgLightBusMessage({
        from_agent: 'user',
        to_agent: targetAgent,
        message: directMessage,
        metadata: {
          source: 'arr_design_ui_direct_agent_command',
          job_id: jobId,
          design_id: evidenceDesignId,
          building_type: buildingType,
          algorithm,
        },
      });
      if (!ownsMessage()) return;
      const [health, log] = await Promise.all([
        getAgLightHealth(),
        getAgLightBusLog(40),
      ]);
      if (!ownsMessage()) return;
      setAgHealth(health);
      setAgBusLog(log);
    } catch (error) {
      if (ownsMessage()) throw error;
    }
  };

  return { agHealth, agBusLog, agReviews, agTrace, agLoading, agError, selectedAgentId, setSelectedAgentId, runAgLightReview, sendDirectAgentMessage };
}
