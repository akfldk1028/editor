import { grammarCriticEvidenceMapping, grammarCriticParticipant } from './grammar-critic-agent';
import { lawGraphEvidenceMapping, lawGraphParticipant } from './law-graph-agent';
import { llmArchitectEvidenceMapping, llmArchitectParticipant } from './llm-architect-agent';
import { maasGeometryEvidenceMapping, maasGeometryParticipant } from './maas-geometry-agent';
import { masterPlanEvidenceMapping, masterPlanParticipant } from './master-plan-agent';
import { massdslEvidenceMapping, massdslParticipant } from './massdsl-agent';
import { parkingEvidenceMapping, parkingParticipant } from './parking-agent';
import { reviewEvidenceMapping, reviewParticipant } from './review-agent';
import type { AgentEvidenceMapping } from './shared/review-adapter';
import type { JsonModuleParticipant } from './shared/team-config';

export interface DesignFlowAgentModule {
  participant: JsonModuleParticipant;
  mapping: AgentEvidenceMapping;
}

export const DESIGN_FLOW_AGENTS: DesignFlowAgentModule[] = [
  {
    participant: lawGraphParticipant,
    mapping: lawGraphEvidenceMapping,
  },
  {
    participant: masterPlanParticipant,
    mapping: masterPlanEvidenceMapping,
  },
  {
    participant: parkingParticipant,
    mapping: parkingEvidenceMapping,
  },
  {
    participant: llmArchitectParticipant,
    mapping: llmArchitectEvidenceMapping,
  },
  {
    participant: massdslParticipant,
    mapping: massdslEvidenceMapping,
  },
  {
    participant: maasGeometryParticipant,
    mapping: maasGeometryEvidenceMapping,
  },
  {
    participant: grammarCriticParticipant,
    mapping: grammarCriticEvidenceMapping,
  },
  {
    participant: reviewParticipant,
    mapping: reviewEvidenceMapping,
  },
];
