import type { AGLightFlowSettings } from './AGLightFlowToolbar';

export type CollaborationLane = 'request' | 'evidence' | 'language' | 'synthesis' | 'review' | 'feedback';

export interface CollaborationTopologyEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  lane: CollaborationLane;
  color: string;
  feedback?: boolean;
}

const LR_POSITIONS: Record<string, { x: number; y: number }> = {
  user: { x: 0, y: 260 },
  design_orchestrator: { x: 240, y: 260 },
  law_graph_agent: { x: 520, y: 70 },
  master_plan_agent: { x: 700, y: 70 },
  parking_agent: { x: 880, y: 70 },
  llm_architect_agent: { x: 520, y: 450 },
  massdsl_agent: { x: 780, y: 450 },
  maas_geometry_agent: { x: 1060, y: 260 },
  grammar_critic_agent: { x: 1320, y: 150 },
  review_agent: { x: 1580, y: 260 },
  end: { x: 1840, y: 260 },
};

const TB_POSITIONS: Record<string, { x: number; y: number }> = {
  user: { x: 360, y: 0 },
  design_orchestrator: { x: 360, y: 150 },
  law_graph_agent: { x: 80, y: 320 },
  master_plan_agent: { x: 80, y: 420 },
  parking_agent: { x: 80, y: 520 },
  llm_architect_agent: { x: 640, y: 320 },
  massdsl_agent: { x: 640, y: 490 },
  maas_geometry_agent: { x: 360, y: 690 },
  grammar_critic_agent: { x: 360, y: 860 },
  review_agent: { x: 360, y: 1030 },
  end: { x: 360, y: 1200 },
};

export const COLLABORATION_TOPOLOGY: readonly CollaborationTopologyEdge[] = [
  { id: 'request', source: 'user', target: 'design_orchestrator', label: 'design request', lane: 'request', color: '#38bdf8' },
  { id: 'evidence-brief', source: 'design_orchestrator', target: 'law_graph_agent', label: 'site + rule query', lane: 'evidence', color: '#38bdf8' },
  { id: 'law-masterplan-a2a', source: 'law_graph_agent', target: 'master_plan_agent', label: 'A2A 법규·배치', lane: 'evidence', color: '#2dd4bf' },
  { id: 'evidence-parking', source: 'master_plan_agent', target: 'parking_agent', label: '배치·주차구획', lane: 'evidence', color: '#2dd4bf' },
  { id: 'language-brief', source: 'design_orchestrator', target: 'llm_architect_agent', label: 'brief + BOOK memory', lane: 'language', color: '#f472b6' },
  { id: 'language-typed', source: 'llm_architect_agent', target: 'massdsl_agent', label: 'typed intent', lane: 'language', color: '#f59e0b' },
  { id: 'evidence-merge', source: 'parking_agent', target: 'maas_geometry_agent', label: 'legal + parking', lane: 'synthesis', color: '#2dd4bf' },
  { id: 'language-merge', source: 'massdsl_agent', target: 'maas_geometry_agent', label: 'geometry AST', lane: 'synthesis', color: '#f59e0b' },
  { id: 'candidate-critic', source: 'maas_geometry_agent', target: 'grammar_critic_agent', label: 'candidate + gates', lane: 'review', color: '#a78bfa' },
  { id: 'critic-review', source: 'grammar_critic_agent', target: 'review_agent', label: 'structured critique', lane: 'review', color: '#c084fc' },
  { id: 'review-feedback', source: 'review_agent', target: 'design_orchestrator', label: 'bounded revision', lane: 'feedback', color: '#22d3ee', feedback: true },
];

export function collaborationNodePosition(
  nodeId: string,
  direction: AGLightFlowSettings['direction'],
  compact: boolean,
) {
  const normalizedId = nodeId === 'masterplan_agent' ? 'master_plan_agent' : nodeId;
  const base = (direction === 'LR' ? LR_POSITIONS : TB_POSITIONS)[normalizedId] || { x: 0, y: 0 };
  const scale = compact ? 0.82 : 1;
  return { x: Math.round(base.x * scale), y: Math.round(base.y * scale) };
}
