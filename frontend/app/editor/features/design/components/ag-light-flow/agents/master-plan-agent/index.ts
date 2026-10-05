import { getTeamParticipant } from '../shared/team-config';
import type { AgentEvidenceMapping } from '../shared/review-adapter';

export const MASTER_PLAN_AGENT_ID = 'master_plan_agent';

export const masterPlanParticipant = getTeamParticipant(MASTER_PLAN_AGENT_ID);

export const masterPlanEvidenceMapping: AgentEvidenceMapping = {
  reviewAgentIds: ['master_plan_agent', 'masterplan_agent'],
  tone: 'parking',
  fallbackLabel: '배치',
};
