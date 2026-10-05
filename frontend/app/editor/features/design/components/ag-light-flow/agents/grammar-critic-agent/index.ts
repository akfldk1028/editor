import { getTeamParticipant } from '../shared/team-config';
import type { AgentEvidenceMapping } from '../shared/review-adapter';

export const GRAMMAR_CRITIC_AGENT_ID = 'grammar_critic_agent';

export const grammarCriticParticipant = getTeamParticipant(GRAMMAR_CRITIC_AGENT_ID);

export const grammarCriticEvidenceMapping: AgentEvidenceMapping = {
  reviewAgentIds: ['grammar_critic_agent'],
  tone: 'critic',
  fallbackLabel: '문법검토',
};
