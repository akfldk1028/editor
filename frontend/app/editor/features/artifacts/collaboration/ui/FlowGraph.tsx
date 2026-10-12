'use client'

import '@xyflow/react/dist/style.css'
import { Background, BackgroundVariant, Controls, type Edge, Handle, MarkerType, type Node, type NodeProps, type NodeTypes, Position, ReactFlow, ReactFlowProvider, useNodesState } from '@xyflow/react'
import { MessagesSquare } from 'lucide-react'
import { useEffect, useMemo } from 'react'

import { markOf, ORCHESTRATOR } from '@/lib/agents'
import { agentLabel } from '@/lib/orchestrator-runs/labels'

import type { CatalogEntry, LiveState } from '../lib/catalog'
import { buildGraph, type GraphNode } from '../lib/graph'
import type { CollaborationMessage } from '../lib/transcript'
import './collaboration.css'

type FlowNodeData = Pick<GraphNode, 'label' | 'sub' | 'kind' | 'order' | 'selected' | 'idle' | 'live'> & { agent: string }
type FlowNode = Node<FlowNodeData, 'agent'>

const LIVE_TITLE: Record<LiveState, string> = { up: '지금 응답함', down: '꺼져 있음', unknown: '상태 미확인' }

/**
 * One participant: its mark, name and whether its service answers, and the last thing it said or what it answers.
 * Everything flows left to right: requests, the person's message and the call order enter on the left upper handle
 * and leave on the right upper one; answers go back on the lower pair.
 */
function AgentNode({ data }: NodeProps<FlowNode>) {
  const Icon = markOf(data.agent).icon
  return (
    <div className="collab-node" data-hub={data.kind === 'hub' ? 'true' : 'false'} data-idle={data.idle ? 'true' : 'false'} data-kind={data.kind} data-selected={data.selected ? 'true' : 'false'}>
      <Handle id="in" isConnectable={false} position={Position.Left} style={{ top: '40%' }} type="target" />
      <Handle id="back" isConnectable={false} position={Position.Left} style={{ top: '62%' }} type="source" />
      <Handle id="out" isConnectable={false} position={Position.Right} style={{ top: '40%' }} type="source" />
      <Handle id="return" isConnectable={false} position={Position.Right} style={{ top: '62%' }} type="target" />
      <header>
        {data.order !== null && <b className="collab-order">{data.order}</b>}
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
  /** The network to draw (the live catalog merged with the conversation's folders); absent = the folders only. */
  catalog?: readonly CatalogEntry[]
  /** Which agents answer right now, by id; absent dots when unknown. */
  live?: Readonly<Record<string, LiveState>>
  /** A smaller canvas for a card inside another artifact; it draws the run's participants only. */
  compact?: boolean
}

/** The flow as it ran: the person → the Orchestrator → the agents it called, left to right and numbered, what was said on dashed moving edges; every other agent waits below. Cards drag and stay where they are dropped. */
export default function FlowGraph({ messages, selected = null, onSelect, catalog, live, compact = false }: Props) {
  const graph = useMemo(() => {
    const spoken = new Set(messages.flatMap((message) => [message.from, message.to]))
    return buildGraph(messages, null, {
      live,
      ...(compact ? { catalog: [...spoken].filter((id) => id !== ORCHESTRATOR).map((id) => catalog?.find((entry) => entry.id === id) ?? { id }) } : catalog ? { catalog } : {}),
    })
  }, [messages, catalog, live, compact])

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([])
  // A new record or catalog lays the cards out again; a selection only restyles them, so a dragged card stays put.
  useEffect(() => {
    setNodes(graph.nodes.map((node) => ({
      id: node.id, type: 'agent', position: node.position, draggable: true,
      data: { label: node.label, sub: node.sub, kind: node.kind, order: node.order, selected: false, idle: node.idle, live: node.live, agent: node.id },
    })))
  }, [graph, setNodes])
  useEffect(() => {
    setNodes((current) => current.map((node) => (node.data.selected === (node.id === selected) ? node : { ...node, data: { ...node.data, selected: node.id === selected } })))
  }, [selected, setNodes])

  const edges = useMemo<Edge[]>(() => graph.edges.map((edge) => {
    const spoken = edge.kind === 'request' || edge.kind === 'response'
    const back = edge.kind === 'response'
    return {
      id: edge.id, source: edge.source, target: edge.target, label: edge.label || undefined, type: 'smoothstep', pathOptions: { borderRadius: 10 },
      sourceHandle: back ? 'back' : 'out', targetHandle: back ? 'return' : 'in',
      animated: spoken, className: `collab-edge-${edge.kind}${edge.known ? '' : ' collab-edge-unknown'}`,
      ...(spoken ? { markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: back ? 'var(--success)' : 'var(--accent)' } } : {}),
    }
  }), [graph])

  const order = useMemo(() => graph.nodes.filter((node) => node.order !== null).sort((a, b) => (a.order ?? 0) - (b.order ?? 0)).map((node) => node.label), [graph])

  if (!graph.nodes.length) {
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
          elementsSelectable
          fitView
          fitViewOptions={{ padding: compact ? 0.25 : 0.1 }}
          maxZoom={1.6}
          minZoom={0.25}
          nodeTypes={nodeTypes}
          nodes={nodes}
          nodesConnectable={false}
          nodesDraggable
          onEdgeClick={(_, edge) => onSelect?.(edge.source === ORCHESTRATOR ? edge.target : edge.source)}
          onNodeClick={(_, node) => onSelect?.(selected === node.id ? null : node.id)}
          onNodesChange={onNodesChange}
          onPaneClick={() => onSelect?.(null)}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} size={1} variant={BackgroundVariant.Dots} />
          <Controls position="bottom-left" showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
      {!compact && <p className="collab-pattern">진행 순서 · {[agentLabel(ORCHESTRATOR), ...order].join(' → ')}</p>}
    </div>
  )
}
