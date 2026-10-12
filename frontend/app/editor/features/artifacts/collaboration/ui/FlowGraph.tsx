'use client'

import '@xyflow/react/dist/style.css'
import { Background, BackgroundVariant, Controls, type Edge, Handle, MarkerType, type Node, type NodeProps, type NodeTypes, Position, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { MessagesSquare } from 'lucide-react'
import { useMemo } from 'react'

import { markOf } from '@/lib/agents'

import { buildGraph, type GraphNode, type LiveState } from '../lib/graph'
import type { CollaborationMessage } from '../lib/transcript'
import './collaboration.css'

type FlowNodeData = Pick<GraphNode, 'label' | 'sub' | 'hub' | 'selected' | 'idle' | 'live'> & { agent: string }
type FlowNode = Node<FlowNodeData, 'agent'>

const LIVE_TITLE: Record<LiveState, string> = { up: '지금 응답함', down: '꺼져 있음', unknown: '상태 미확인' }

/** One participant: its mark, name and whether its service answers, and the last thing it said or what it answers. Requests leave the hub on the right and enter an agent on the left; answers go back the other way. */
function AgentNode({ data }: NodeProps<FlowNode>) {
  const Icon = markOf(data.agent).icon
  return (
    <div className="collab-node" data-hub={data.hub ? 'true' : 'false'} data-idle={data.idle ? 'true' : 'false'} data-selected={data.selected ? 'true' : 'false'}>
      <Handle id="req-out" isConnectable={false} position={Position.Right} style={{ top: '38%' }} type="source" />
      <Handle id="res-in" isConnectable={false} position={Position.Right} style={{ top: '66%' }} type="target" />
      <Handle id="req-in" isConnectable={false} position={Position.Left} style={{ top: '38%' }} type="target" />
      <Handle id="res-out" isConnectable={false} position={Position.Left} style={{ top: '66%' }} type="source" />
      <header>
        <Icon aria-hidden="true" size={14} />
        <span>{data.label}</span>
        {data.live && <span className="collab-live" data-state={data.live} title={LIVE_TITLE[data.live]} />}
      </header>
      {data.sub && <p>{data.sub}</p>}
    </div>
  )
}

const nodeTypes: NodeTypes = { agent: AgentNode }

interface Props {
  messages: readonly CollaborationMessage[]
  selected?: string | null
  onSelect?: (agent: string | null) => void
  /** Which agents answer right now, by id; absent dots when unknown. */
  live?: Readonly<Record<string, LiveState>>
  /** A smaller canvas for a card inside another artifact; it draws the run's participants only. */
  compact?: boolean
}

/** The network as a graph: the Orchestrator and every agent, right-angled edges for what this run said, one per direction and pair. */
export default function FlowGraph({ messages, selected = null, onSelect, live, compact = false }: Props) {
  const { nodes, edges } = useMemo(() => {
    const spoken = new Set(messages.flatMap((message) => [message.from, message.to]))
    const graph = buildGraph(messages, selected, { live, ...(compact ? { catalog: [...spoken].filter((id) => id !== 'orchestrator').map((id) => ({ id })) } : {}) })
    const nodes: FlowNode[] = graph.nodes.map((node) => ({
      id: node.id, type: 'agent', position: node.position, draggable: true,
      data: { label: node.label, sub: node.sub, hub: node.hub, selected: node.selected, idle: node.idle, live: node.live, agent: node.id },
    }))
    const edges: Edge[] = graph.edges.map((edge) => ({
      id: edge.id, source: edge.source, target: edge.target, label: edge.label, type: 'smoothstep', pathOptions: { borderRadius: 10 },
      sourceHandle: edge.kind === 'request' ? 'req-out' : 'res-out', targetHandle: edge.kind === 'request' ? 'req-in' : 'res-in',
      className: `collab-edge-${edge.kind}${edge.known ? '' : ' collab-edge-unknown'}`,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: edge.kind === 'request' ? 'var(--accent)' : 'var(--success)' },
    }))
    return { nodes, edges }
  }, [messages, selected, live, compact])

  if (!nodes.length) {
    return (
      <div className="collab-graph collab-empty" data-compact={compact ? 'true' : 'false'}>
        <MessagesSquare aria-hidden="true" size={22} />
        <span>아직 주고받은 요청·응답이 없어요</span>
      </div>
    )
  }
  return (
    <div className="collab-graph" data-compact={compact ? 'true' : 'false'} data-edge-count={edges.length} data-node-count={nodes.length}>
      <ReactFlowProvider>
        <ReactFlow
          edges={edges}
          elementsSelectable={false}
          fitView
          fitViewOptions={{ padding: compact ? 0.25 : 0.12 }}
          maxZoom={1.6}
          minZoom={0.3}
          nodeTypes={nodeTypes}
          nodes={nodes}
          nodesConnectable={false}
          onNodeClick={(_, node) => onSelect?.(selected === node.id ? null : node.id)}
          onPaneClick={() => onSelect?.(null)}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} size={1} variant={BackgroundVariant.Dots} />
          <Controls position="bottom-left" showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  )
}
