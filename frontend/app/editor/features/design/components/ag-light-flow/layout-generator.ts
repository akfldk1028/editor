import type { AGLightFlowSettings } from './AGLightFlowToolbar';
import { DESIGN_FLOW_AGENTS } from './agents';
import {
  COLLABORATION_TOPOLOGY,
  collaborationNodePosition,
} from './collaboration-topology';
import {
  createJsonAgentNode,
  getAgentMessageIds,
  getMessagesForAgent,
} from './agents/shared/review-adapter';
import {
  createEdge,
  createEndNode,
  createUserNode,
  type AGLightEdge,
  type AGLightMessage,
  type AGLightNode,
  type AGLightReview,
  type AGLightRunStatus,
  NODE_DIMENSIONS,
} from './types';

export type AGLightViewMode = 'pattern' | 'execution';

interface LayoutInput {
  reviews: AGLightReview[];
  messages?: AGLightMessage[];
  status: AGLightRunStatus;
  viewMode: AGLightViewMode;
  settings: AGLightFlowSettings;
  isFullscreen?: boolean;
  selectedAgentId?: string;
  onSelectAgent?: (agentId: string) => void;
}

const HUB_ID = 'design_orchestrator';

const createHubNode = (
  position: { x: number; y: number },
  status: AGLightRunStatus,
  isProcessing: boolean,
  compact: boolean
): AGLightNode => ({
  id: HUB_ID,
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
    label: HUB_ID,
    agentType: 'Selector/Handoff',
    description: '법규-설계 협업 라우터',
    isActive: true,
    status,
    reason: null,
    draggable: !isProcessing,
    tone: 'hub',
    compact,
  },
});

export function generateAGLightLayout({
  reviews,
  messages,
  status,
  viewMode,
  settings,
  isFullscreen = false,
  selectedAgentId,
  onSelectAgent,
}: LayoutInput): { nodes: AGLightNode[]; edges: AGLightEdge[] } {
  const nodes: AGLightNode[] = [];
  const edges: AGLightEdge[] = [];
  const isProcessing = status === 'active' || status === 'awaiting_input';
  const compact = !isFullscreen;

  const userNode = createUserNode(
    collaborationNodePosition('user', settings.direction, compact),
    true,
    isProcessing,
  );
  userNode.data.compact = compact;
  nodes.push(userNode);
  nodes.push(createHubNode(
    collaborationNodePosition(HUB_ID, settings.direction, compact),
    status,
    isProcessing,
    compact,
  ));

  DESIGN_FLOW_AGENTS.forEach((agent) => {
    const agentId = agent.participant.config.name;
    nodes.push(createJsonAgentNode({
      participant: agent.participant,
      mapping: agent.mapping,
      reviews,
      messages,
      settings,
      position: collaborationNodePosition(agentId, settings.direction, compact),
      isProcessing,
      compact,
      selectedAgentId,
      onSelectAgent,
    }));
  });

  const agentById = new Map(
    DESIGN_FLOW_AGENTS.map((agent) => [agent.participant.config.name, agent]),
  );
  COLLABORATION_TOPOLOGY.forEach((topologyEdge) => {
    const targetAgent = agentById.get(topologyEdge.target);
    const agentMessages = targetAgent
      ? getMessagesForAgent(messages, getAgentMessageIds(targetAgent.participant, targetAgent.mapping))
      : (messages || []).filter((message) => (
        message.from_agent === topologyEdge.source && message.to_agent === topologyEdge.target
      ));
    const active = topologyEdge.id === 'request' || agentMessages.length > 0 || Boolean(targetAgent && reviews.some((review) =>
      targetAgent.mapping.reviewAgentIds.includes(review.agent) &&
      (review.status === 'pass' || review.status === 'check')
    ));

    edges.push(createEdge(`flow-${topologyEdge.id}`, topologyEdge.source, topologyEdge.target, {
      animated: active,
      label: settings.showLabels ? topologyEdge.label : '',
      messages: agentMessages,
      routingType: topologyEdge.feedback ? 'feedback' : 'primary',
      stroke: active ? topologyEdge.color : '#475569',
      strokeWidth: active ? 2.2 : 1.2,
      strokeDasharray: topologyEdge.feedback ? '7 7' : undefined,
      opacity: active ? 1 : 0.52,
    }));
  });

  if (viewMode === 'execution' && messages?.length) {
    const lastMessage = messages[messages.length - 1];
    const endNode = createEndNode(
      collaborationNodePosition('end', settings.direction, compact),
      status,
    );
    endNode.data.compact = compact;
    nodes.push(endNode);
    endNode.data.reason = lastMessage?.message || '';
    edges.push(createEdge('review-end', 'review_agent', 'end', {
      label: settings.showLabels ? 'done' : '',
      messages,
      routingType: 'primary',
      stroke: status === 'complete' ? '#22c55e' : '#ef4444',
      strokeWidth: 2,
    }));
  }

  return { nodes, edges };
}
