'use client'

import '@xyflow/react/dist/style.css'
import { Background, BackgroundVariant, Controls, type Edge, Handle, MarkerType, type Node, type NodeProps, type NodeTypes, Position, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { MessagesSquare } from 'lucide-react'
import { useMemo } from 'react'

import { markOf } from '@/lib/agents'

import { buildGraph, type GraphNode } from '../lib/graph'
import type { CollaborationMessage } from '../lib/transcript'
import './collaboration.css'

type FlowNodeData = Pick<GraphNode, 'label' | 'sub' | 'hub' | 'selected'> & { agent: string }
type FlowNode = Node<FlowNodeData, 'agent'>

/** One participant: its mark and name, and the last thing it said or was asked. Handles: requests leave the hub on the right and enter an agent on the left; answers go back the other way. */
function AgentNode({ data }: NodeProps<FlowNode>) {
  const Icon = markOf(data.agent).icon
  return (
    <div className="collab-node" data-hub={data.hub ? 'true' : 'false'} data-selected={data.selected ? 'true' : 'false'}>
      <Handle id="req-out" isConnectable={false} position={Position.Right} style={{ top: '38%' }} type="source" />
      <Handle id="res-in" isConnectable={false} position={Position.Right} style={{ top: '66%' }} type="target" />
      <Handle id="req-in" isConnectable={false} position={Position.Left} style={{ top: '38%' }} type="target" />
      <Handle id="res-out" isConnectable={false} position={Position.Left} style={{ top: '66%' }} type="source" />
      <header><Icon aria-hidden="true" size={14} /><span>{data.label}</span></header>
      {data.sub && <p>{data.sub}</p>}
    </div>
  )
}

const nodeTypes: NodeTypes = { agent: AgentNode }

interface Props {
  messages: readonly CollaborationMessage[]
  selected?: string | null
  onSelect?: (agent: string | null) => void
  /** A smaller canvas for a card inside another artifact. */
  compact?: boolean
}

/** The run as a graph: the Orchestrator and the agents it spoke with, one line per direction and pair, labelled with what and how many. */
export default function FlowGraph({ messages, selected = null, onSelect, compact = false }: Props) {
  const { nodes, edges } = useMemo(() => {
    const graph = buildGraph(messages, selected)
    const nodes: FlowNode[] = graph.nodes.map((node) => ({
      id: node.id, type: 'agent', position: node.position, draggable: true,
      data: { label: node.label, sub: node.sub, hub: node.hub, selected: node.selected, agent: node.id },
    }))
    const edges: Edge[] = graph.edges.map((edge) => ({
      id: edge.id, source: edge.source, target: edge.target, label: edge.label,
      sourceHandle: edge.kind === 'request' ? 'req-out' : 'res-out', targetHandle: edge.kind === 'request' ? 'req-in' : 'res-in',
      className: `collab-edge-${edge.kind}${edge.known ? '' : ' collab-edge-unknown'}`,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: edge.kind === 'request' ? 'var(--accent)' : 'var(--success)' },
    }))
    return { nodes, edges }
  }, [messages, selected])

  if (!nodes.length) {
    return (
      <div className="collab-graph collab-empty" data-compact={compact ? 'true' : 'false'}>
        <MessagesSquare aria-hidden="true" size={22} />
        <span>아직 주고받은 요청·응답이 없어요</span>
      </div>
    )
  }
  return (
    <div className="collab-graph" data-compact={compact ? 'true' : 'false'} data-node-count={nodes.length} data-edge-count={edges.length}>
      <ReactFlowProvider>
        <ReactFlow
          edges={edges}
          elementsSelectable={false}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          maxZoom={1.6}
          minZoom={0.4}
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
