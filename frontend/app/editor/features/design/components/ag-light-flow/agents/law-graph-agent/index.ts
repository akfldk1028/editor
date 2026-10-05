import { getTeamParticipant } from '../shared/team-config';
import type { AgentEvidenceMapping } from '../shared/review-adapter';

export const LAW_GRAPH_AGENT_ID = 'law_graph_agent';

export const lawGraphParticipant = getTeamParticipant(LAW_GRAPH_AGENT_ID);

export const lawGraphEvidenceMapping: AgentEvidenceMapping = {
  reviewAgentIds: ['law_graph_agent', 'law_agent'],
  tone: 'law',
  fallbackLabel: '법규',
};
