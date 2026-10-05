import { getTeamParticipant } from '../shared/team-config';
import type { AgentEvidenceMapping } from '../shared/review-adapter';

export const MAAS_GEOMETRY_AGENT_ID = 'maas_geometry_agent';

export const maasGeometryParticipant = getTeamParticipant(MAAS_GEOMETRY_AGENT_ID);

export const maasGeometryEvidenceMapping: AgentEvidenceMapping = {
  reviewAgentIds: ['maas_geometry_agent', 'sunlight_agent', 'datum_agent'],
  tone: 'sunlight',
  fallbackLabel: '매스/기준면',
};
