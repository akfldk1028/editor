import { useEffect, useState } from 'react';
import { getAgLightBusLog, getAgLightHealth, getDesignEvidence, sendAgLightBusMessage, type AgLightBusEvent, type AgLightHealth } from '../lib/api-client';
import { buildAgentTrace, getMassLegalStatus, makeAgentReviews, type AgentTrace } from '../lib/ag-light-collaboration';
import type { AGLightReview } from '../components/ag-light-flow/types';
import type { InteractiveDesignProps } from './use-interactive-design';

type AgentReviewInput = Pick<InteractiveDesignProps, 'jobId' | 'design' | 'massGeojson' | 'setbackGeometries' | 'buildingType' | 'algorithm' | 'onAestheticGenerated' | 'onPreviewCandidate'>;

export function useInteractiveAgentReview({ jobId, design, massGeojson, setbackGeometries, buildingType, algorithm, onAestheticGenerated, onPreviewCandidate }: AgentReviewInput) {
  const [agHealth, setAgHealth] = useState<AgLightHealth | null>(null);
  const [agBusLog, setAgBusLog] = useState<AgLightBusEvent[]>([]);
  const [agReviews, setAgReviews] = useState<AGLightReview[]>([]);
  const [agTrace, setAgTrace] = useState<AgentTrace[]>([]);
  const [agLoading, setAgLoading] = useState(false);
  const [agError, setAgError] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState('law_graph_agent');

  useEffect(() => {
    setAgReviews([]);
    setAgTrace([]);
    setAgError('');
  }, [design.id, onAestheticGenerated, onPreviewCandidate]);

  useEffect(() => {
    let cancelled = false;
    const refreshAgLight = async () => {
      try {
        const [health, log] = await Promise.all([
          getAgLightHealth(),
          getAgLightBusLog(20),
        ]);
        if (!cancelled) {
          setAgHealth(health);
          setAgBusLog(log);
          setAgError('');
        }
      } catch (e) {
        if (!cancelled) setAgError(e instanceof Error ? e.message : 'AG-light 연결 실패');
      }
    };
    refreshAgLight();
    return () => {
      cancelled = true;
    };
  }, [design.id]);

  const runAgLightReview = async () => {
    if (!jobId) {
      setAgError('저장된 최적화 job이 있어야 AG-light 검토를 실행할 수 있습니다.');
      return;
    }
    const rawDesignId = massGeojson?.properties?.design_id;
    const evidenceDesignId = typeof rawDesignId === 'number' ? rawDesignId : design.id;
    setAgLoading(true);
    setAgError('');
    try {
      const evidence = await getDesignEvidence(jobId, evidenceDesignId);
      const reviews = makeAgentReviews(evidence, massGeojson, setbackGeometries);
      const trace = buildAgentTrace(reviews, evidence, massGeojson, setbackGeometries);
      const metadata = {
        job_id: jobId,
        design_id: evidenceDesignId,
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
      setAgReviews(reviews);
      setAgTrace(trace);
      const [health, log] = await Promise.all([
        getAgLightHealth(),
        getAgLightBusLog(40),
      ]);
      setAgHealth(health);
      setAgBusLog(log);
    } catch (e) {
      const fallbackReviews = makeAgentReviews(null, massGeojson, setbackGeometries);
      const fallbackTrace = buildAgentTrace(fallbackReviews, null, massGeojson, setbackGeometries);
      setAgReviews(fallbackReviews);
      setAgTrace(fallbackTrace);
      setAgError(e instanceof Error ? e.message : 'AG-light 검토 실패');
    } finally {
      setAgLoading(false);
    }
  };

  const sendDirectAgentMessage = async (targetAgent: string, directMessage: string) => {
    const rawDesignId = massGeojson?.properties?.design_id;
    const evidenceDesignId = typeof rawDesignId === 'number' ? rawDesignId : design.id;
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
    const [health, log] = await Promise.all([
      getAgLightHealth(),
      getAgLightBusLog(40),
    ]);
    setAgHealth(health);
    setAgBusLog(log);
  };

  return { agHealth, agBusLog, agReviews, agTrace, agLoading, agError, selectedAgentId, setSelectedAgentId, runAgLightReview, sendDirectAgentMessage };
}
