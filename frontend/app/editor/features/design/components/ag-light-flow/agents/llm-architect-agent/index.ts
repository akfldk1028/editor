import { getTeamParticipant } from '../shared/team-config';
import type { AgentEvidenceMapping } from '../shared/review-adapter';

export const LLM_ARCHITECT_AGENT_ID = 'llm_architect_agent';

export const llmArchitectParticipant = getTeamParticipant(LLM_ARCHITECT_AGENT_ID);

export const llmArchitectEvidenceMapping: AgentEvidenceMapping = {
  reviewAgentIds: ['llm_architect_agent'],
  tone: 'sunlight',
  fallbackLabel: 'LLM 건축언어',
};
