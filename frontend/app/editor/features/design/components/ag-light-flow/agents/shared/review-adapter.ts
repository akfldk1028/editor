import { requiredValue } from '../../../../lib/required-value';
import type { AGLightFlowSettings } from '../../AGLightFlowToolbar';
import type {
  AGLightMessage,
  AGLightNode,
  AGLightNodeData,
  AGLightReview,
} from '../../types';
import { NODE_DIMENSIONS } from '../../types';
import type { JsonModuleParticipant } from './team-config';

export interface AgentEvidenceMapping {
  reviewAgentIds: string[];
  tone: NonNullable<AGLightNodeData['tone']>;
  fallbackLabel?: string;
}

export const getAgentMessageIds = (participant: JsonModuleParticipant, mapping: AgentEvidenceMapping) =>
  Array.from(new Set([participant.config.name, ...mapping.reviewAgentIds]));

export const getLastAgentMessage = (messages: AGLightMessage[] | undefined, agentIds: string[]) => {
  const message = messages
    ?.slice()
    .reverse()
    .find((item) => agentIds.includes(item.from_agent) || agentIds.includes(item.to_agent));
  if (!message?.message) return undefined;
  return message.message.length > 96 ? `${message.message.slice(0, 93)}...` : message.message;
};

export const getMessagesForAgent = (messages: AGLightMessage[] | undefined, agentIds: string[]) =>
  messages?.filter((msg) => agentIds.includes(msg.from_agent) || agentIds.includes(msg.to_agent)) || [];

const getMappedReviews = (reviews: AGLightReview[], agentIds: string[]) =>
  reviews.filter((review) => agentIds.includes(review.agent));

const getIsActive = (reviews: AGLightReview[]) =>
  reviews.some((review) => review.status === 'pass' || review.status === 'check');

const getSummary = (
  participant: JsonModuleParticipant,
  reviews: AGLightReview[],
  settings: AGLightFlowSettings
) => {
  if (!reviews.length) return participant.config.description || participant.description || '';
  if (reviews.length === 1) return requiredValue(reviews[0]).summary;
  if (!settings.showLabels) return reviews.map((review) => review.label).join(' / ');
  return reviews.map((review) => `${review.label}: ${review.summary}`).join(' | ');
};

const getDetail = (participant: JsonModuleParticipant, reviews: AGLightReview[]) => {
  if (!reviews.length) return participant.config.system_message || participant.config.description || null;
  return reviews.map((review) => `${review.label}: ${review.detail}`).join('\n');
};

export const createJsonAgentNode = ({
  participant,
  mapping,
  reviews,
  messages,
  settings,
  position,
  isProcessing,
  compact,
  selectedAgentId,
  onSelectAgent,
}: {
  participant: JsonModuleParticipant;
  mapping: AgentEvidenceMapping;
  reviews: AGLightReview[];
  messages?: AGLightMessage[];
  settings: AGLightFlowSettings;
  position: { x: number; y: number };
  isProcessing: boolean;
  compact: boolean;
  selectedAgentId?: string;
  onSelectAgent?: (agentId: string) => void;
}): AGLightNode => {
  const mappedReviews = getMappedReviews(reviews, mapping.reviewAgentIds);
  const primaryReview = mappedReviews[0];
  const messageAgentIds = getAgentMessageIds(participant, mapping);

  return {
    id: participant.config.name,
    type: 'agLightNode',
    position,
    width: compact ? NODE_DIMENSIONS.compact.width : NODE_DIMENSIONS.default.width,
    height: compact ? NODE_DIMENSIONS.compact.height : NODE_DIMENSIONS.default.height,
    initialWidth: compact ? NODE_DIMENSIONS.compact.width : NODE_DIMENSIONS.default.width,
    initialHeight: compact ? NODE_DIMENSIONS.compact.height : NODE_DIMENSIONS.default.height,
    style: {
      width: compact ? NODE_DIMENSIONS.compact.width : NODE_DIMENSIONS.default.width,
      height: compact ? NODE_DIMENSIONS.compact.height : NODE_DIMENSIONS.default.height,
    },
    data: {
      type: 'agent',
      label: mapping.fallbackLabel || primaryReview?.label || participant.label,
      agentType: participant.config.name,
      description: getSummary(participant, mappedReviews, settings),
      isActive: getIsActive(mappedReviews),
      status: null,
      reason: getDetail(participant, mappedReviews),
      draggable: !isProcessing,
      tone: mapping.tone,
      lastMessage: getLastAgentMessage(messages, messageAgentIds),
      review: primaryReview,
      compact,
      jsonModuleAgent: participant.config.name,
      selected: selectedAgentId === participant.config.name,
      onSelectAgent,
    },
  };
};
