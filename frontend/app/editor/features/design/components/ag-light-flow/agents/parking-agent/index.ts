import { getTeamParticipant } from '../shared/team-config';
import type { AgentEvidenceMapping } from '../shared/review-adapter';

export const PARKING_AGENT_ID = 'parking_agent';

export const parkingParticipant = getTeamParticipant(PARKING_AGENT_ID);

export const parkingEvidenceMapping: AgentEvidenceMapping = {
  reviewAgentIds: ['parking_agent'],
  tone: 'parking',
  fallbackLabel: '주차',
};
