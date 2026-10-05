import type { Edge, Node } from '@xyflow/react';

export type AGLightNodeType = 'user' | 'agent' | 'end';

export type AGLightReview = {
  agent: string;
  label: string;
  status: 'pass' | 'check' | 'fail' | 'info';
  summary: string;
  detail: string;
};

export type AGLightMessage = {
  timestamp?: string;
  from_agent: string;
  to_agent: string;
  message: string;
  event_type?: string;
  metadata?: Record<string, unknown>;
};

export type AGLightRunStatus = 'idle' | 'active' | 'awaiting_input' | 'complete' | 'error' | 'stopped';

export interface AGLightNodeData {
  [key: string]: unknown;
  type: AGLightNodeType;
  label: string;
  agentType?: string;
  description?: string;
  isActive?: boolean;
  status?: AGLightRunStatus | null;
  reason?: string | null;
  draggable: boolean;
  tone?: 'law' | 'parking' | 'sunlight' | 'datum' | 'critic' | 'hub';
  review?: AGLightReview;
  jsonModuleAgent?: string;
  selected?: boolean;
  onSelectAgent?: (agentId: string) => void;
}

export interface AGLightEdgeData extends Record<string, unknown> {
  label?: string;
  messages: AGLightMessage[];
  routingType?: 'primary' | 'secondary' | 'feedback';
  bidirectionalPair?: string;
  onClick?: () => void;
}

export type AGLightEdge = Edge<AGLightEdgeData>;
export type AGLightNode = Node<AGLightNodeData>;

export const NODE_DIMENSIONS = {
  compact: { width: 136, height: 78 },
  default: { width: 176, height: 102 },
  end: { width: 176, height: 82 },
};

export const createNode = (
  id: string,
  type: AGLightNodeType,
  label: string,
  description: string,
  position: { x: number; y: number },
  options: {
    isActive: boolean;
    isProcessing: boolean;
    status?: AGLightRunStatus | null;
    reason?: string | null;
    tone?: AGLightNodeData['tone'];
    review?: AGLightReview;
  }
): AGLightNode => {
  const dimensions = type === 'end' ? NODE_DIMENSIONS.end : NODE_DIMENSIONS.default;
  return {
    id,
    type: 'agLightNode',
    position,
    width: dimensions.width,
    height: dimensions.height,
    initialWidth: dimensions.width,
    initialHeight: dimensions.height,
    style: {
      width: dimensions.width,
      height: dimensions.height,
    },
    data: {
      type,
      label,
      agentType: type === 'user' ? 'user' : label,
      description,
      isActive: options.isActive,
      status: options.status ?? null,
      reason: options.reason ?? null,
      draggable: !options.isProcessing,
      tone: options.tone,
      review: options.review,
    },
  };
};

export const createUserNode = (
  position: { x: number; y: number },
  isActive: boolean,
  isProcessing: boolean
): AGLightNode =>
  createNode('user', 'user', 'User', 'Human user', position, {
    isActive,
    isProcessing,
    tone: 'hub',
  });

export const createEndNode = (
  position: { x: number; y: number },
  status?: AGLightRunStatus | null
): AGLightNode =>
  createNode('end', 'end', 'End', '', position, {
    isActive: false,
    isProcessing: false,
    status: status ?? 'idle',
    tone: 'hub',
  });

export const createEdge = (
  id: string,
  source: string,
  target: string,
  options: {
    animated?: boolean;
    stroke?: string;
    strokeWidth?: number;
    strokeDasharray?: string;
    opacity?: number;
    label?: string;
    routingType?: 'primary' | 'secondary' | 'feedback';
    messages?: AGLightMessage[];
  } = {}
): AGLightEdge => ({
  id,
  source,
  target,
  type: 'smoothstep',
  animated: options.animated || false,
  label: options.label || undefined,
  data: {
    label: options.label || '',
    messages: options.messages || [],
    routingType: options.routingType,
  },
  style: {
    stroke: options.stroke || '#2563eb',
    strokeWidth: options.strokeWidth || 1,
    strokeDasharray: options.strokeDasharray,
    opacity: options.opacity || 1,
  },
});
