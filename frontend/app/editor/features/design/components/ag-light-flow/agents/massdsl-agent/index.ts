import { getTeamParticipant } from '../shared/team-config';
import type { AgentEvidenceMapping } from '../shared/review-adapter';

export const MASSDSL_AGENT_ID = 'massdsl_agent';

export const massdslParticipant = getTeamParticipant(MASSDSL_AGENT_ID);

export const massdslEvidenceMapping: AgentEvidenceMapping = {
  reviewAgentIds: ['massdsl_agent'],
  tone: 'sunlight',
  fallbackLabel: 'MassDSL',
};
