import { getTeamParticipant } from '../shared/team-config';
import type { AgentEvidenceMapping } from '../shared/review-adapter';

export const REVIEW_AGENT_ID = 'review_agent';

export const reviewParticipant = getTeamParticipant(REVIEW_AGENT_ID);

export const reviewEvidenceMapping: AgentEvidenceMapping = {
  reviewAgentIds: ['review_agent', 'design_critic'],
  tone: 'critic',
  fallbackLabel: '최종검토',
};
