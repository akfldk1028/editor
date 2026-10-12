'use client'

import '@xyflow/react/dist/style.css'
import { Background, BackgroundVariant, Controls, type Edge, Handle, MarkerType, type Node, type NodeProps, type NodeTypes, Position, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { MessagesSquare } from 'lucide-react'
import { useMemo } from 'react'

import { markOf } from '@/lib/agents'

import type { CatalogEntry, LiveState } from '../lib/catalog'
import { buildGraph, callOrder, type GraphNode, type Side } from '../lib/graph'
import type { CollaborationMessage } from '../lib/transcript'
import './collaboration.css'

type FlowNodeData = Pick<GraphNode, 'label' | 'sub' | 'kind' | 'order' | 'selected' | 'idle' | 'live'> & { agent: string }
type FlowNode = Node<FlowNodeData, 'agent'>

const LIVE_TITLE: Record<LiveState, string> = { up: '지금 응답함', down: '꺼져 있음', unknown: '상태 미확인' }
const POSITION: Record<Side, Position> = { left: Position.Left, right: Position.Right, top: Position.Top, bottom: Position.Bottom }
const OPPOSITE: Record<Side, Side> = { left: 'right', right: 'left', top: 'bottom', bottom: 'top' }
const SIDES: Side[] = ['left', 'right', 'top', 'bottom']
/** Two handles per side: requests leave/enter at the first, answers at the second, so a pair of edges runs side by side. */
const offset = (side: Side, which: 'a' | 'b') => (side === 'left' || side === 'right' ? { top: which === 'a' ? '40%' : '62%' } : { left: which === 'a' ? '40%' : '62%' })

/** One participant: its mark, name and whether its service answers, and the last thing it said or what it answers. */
function AgentNode({ data }: NodeProps<FlowNode>) {
  const Icon = markOf(data.agent).icon
  return (
    <div className="collab-node" data-hub={data.kind === 'hub' ? 'true' : 'false'} data-idle={data.idle ? 'true' : 'false'} data-kind={data.kind} data-selected={data.selected ? 'true' : 'false'}>
      {SIDES.map((side) => (
        <span key={side}>
          <Handle id={`${side}-a-out`} isConnectable={false} position={POSITION[side]} style={offset(side, 'a')} type="source" />
          <Handle id={`${side}-a-in`} isConnectable={false} position={POSITION[side]} style={offset(side, 'a')} type="target" />
          <Handle id={`${side}-b-out`} isConnectable={false} position={POSITION[side]} style={offset(side, 'b')} type="source" />
          <Handle id={`${side}-b-in`} isConnectable={false} position={POSITION[side]} style={offset(side, 'b')} type="target" />
        </span>
      ))}
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

/** The flow as it ran: the person → the Orchestrator → the agents it called, left to right and numbered, what was said on dashed moving edges; every other agent waits below. Cards drag. */
export default function FlowGraph({ messages, selected = null, onSelect, catalog, live, compact = false }: Props) {
  const { nodes, edges } = useMemo(() => {
    const spoken = new Set(messages.flatMap((message) => [message.from, message.to]))
    const graph = buildGraph(messages, selected, {
      live,
      ...(compact ? { catalog: [...spoken].filter((id) => id !== 'orchestrator').map((id) => catalog?.find((entry) => entry.id === id) ?? { id }) } : catalog ? { catalog } : {}),
    })
    const sides = new Map(graph.nodes.map((node) => [node.id, node.side]))
    const nodes: FlowNode[] = graph.nodes.map((node) => ({
      id: node.id, type: 'agent', position: node.position, draggable: true,
      data: { label: node.label, sub: node.sub, kind: node.kind, order: node.order, selected: node.selected, idle: node.idle, live: node.live, agent: node.id },
    }))
    const edges: Edge[] = graph.edges.map((edge) => {
      // The hub leaves on the side the other party sits on; the other party receives on the facing side.
      // Everything runs left to right: requests and the 'next' order on the upper lane, answers back on the lower lane.
      const hubSide = sides.get(edge.source === 'orchestrator' ? edge.target : edge.source) ?? 'right'
      const fromHub = edge.source === 'orchestrator'
      const lane = edge.kind === 'response' ? 'b' : 'a'
      const sourceSide: Side = edge.kind === 'user' || edge.kind === 'next' ? 'right' : fromHub ? hubSide : OPPOSITE[hubSide]
      const targetSide: Side = edge.kind === 'user' || edge.kind === 'next' ? 'left' : fromHub ? OPPOSITE[hubSide] : hubSide
      const spoken = edge.kind === 'request' || edge.kind === 'response'
      return {
        id: edge.id, source: edge.source, target: edge.target, label: edge.label || undefined, type: 'smoothstep', pathOptions: { borderRadius: 10 },
        sourceHandle: `${sourceSide}-${lane}-out`, targetHandle: `${targetSide}-${lane}-in`,
        animated: spoken, className: `collab-edge-${edge.kind}${edge.known ? '' : ' collab-edge-unknown'}`,
        ...(spoken ? { markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: edge.kind === 'request' ? 'var(--accent)' : 'var(--success)' } } : {}),
      }
    })
    return { nodes, edges }
  }, [messages, selected, catalog, live, compact])

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
          elementsSelectable
          fitView
          fitViewOptions={{ padding: compact ? 0.25 : 0.1 }}
          maxZoom={1.6}
          minZoom={0.25}
          nodeTypes={nodeTypes}
          nodes={nodes}
          nodesConnectable={false}
          nodesDraggable
          onEdgeClick={(_, edge) => onSelect?.(edge.source === 'orchestrator' ? edge.target : edge.source)}
          onNodeClick={(_, node) => onSelect?.(selected === node.id ? null : node.id)}
          onPaneClick={() => onSelect?.(null)}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} size={1} variant={BackgroundVariant.Dots} />
          <Controls position="bottom-left" showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
      {!compact && <p className="collab-pattern">진행 순서 · {[ 'Orchestrator Agent', ...callOrder(messages).map((id) => nodes.find((node) => node.id === id)?.data.label ?? id)].join(' → ')}</p>}
    </div>
  )
}
