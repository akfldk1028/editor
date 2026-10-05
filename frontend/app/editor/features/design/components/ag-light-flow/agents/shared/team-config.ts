import maasLegalDesignTeam from './maas-legal-design-team.json';

export interface JsonModuleParticipant {
  provider: string;
  component_type: 'agent' | string;
  label: string;
  description?: string;
  config: {
    name: string;
    description?: string;
    system_message?: string;
    handoffs?: string[];
  };
}

export interface JsonModuleTeam {
  provider: string;
  component_type: 'team' | string;
  label: string;
  description?: string;
  config: {
    name: string;
    description?: string;
    participants: JsonModuleParticipant[];
    selector_prompt?: string;
  };
}

export const MAAS_LEGAL_DESIGN_TEAM = maasLegalDesignTeam as JsonModuleTeam;

export const getTeamParticipants = (): JsonModuleParticipant[] =>
  MAAS_LEGAL_DESIGN_TEAM.config.participants;

export const getTeamParticipant = (name: string): JsonModuleParticipant => {
  const participant = getTeamParticipants().find((item) => item.config.name === name);
  if (!participant) {
    if (name === 'master_plan_agent' || name === 'masterplan_agent') {
      return {
        provider: 'autogenstudio.a2a.A2AAgent',
        component_type: 'agent',
        label: 'Master Plan Agent (대지배치)',
        description: '건축 배치, 코어, 주차 구획 기하 합성 및 GIS 3D 맥락 분석 에이전트',
        config: {
          name: 'master_plan_agent',
          description: 'Lawagent 임계치 기반 건물 Footprint, 25% 코어, 8대 주차구획 자동 배치 및 GeoJSON/PNG 도면 생성',
        },
      };
    }
    throw new Error(`Missing JSON_MODULES MAAS participant: ${name}`);
  }
  return participant;
};
