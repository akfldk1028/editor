'use client'

import '@xyflow/react/dist/style.css'
import { Background, BackgroundVariant, BaseEdge, Controls, type Edge, EdgeLabelRenderer, type EdgeProps, type EdgeTypes, getSmoothStepPath, Handle, MarkerType, type Node, type NodeProps, type NodeTypes, Position, ReactFlow, ReactFlowProvider, type Rect, useNodesState, useReactFlow } from '@xyflow/react'
import { MessagesSquare } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { markOf, ORCHESTRATOR, USER } from '@/lib/agents'
import { agentLabel } from '@/lib/orchestrator-runs/labels'

import type { CatalogEntry, LiveState } from '../lib/catalog'
import { buildGraph, CARD_HEIGHT, CARD_WIDTH, type GraphNode, NODE_HEIGHT, NODE_WIDTH } from '../lib/graph'
import type { CollaborationMessage } from '../lib/transcript'
import './collaboration.css'

type FlowNodeData = Pick<GraphNode, 'label' | 'sub' | 'kind' | 'order' | 'selected' | 'idle' | 'live' | 'said'> & { agent: string }
type FlowNode = Node<FlowNodeData, 'agent' | 'said'>

/** Below this width the flow stacks into one column; wider canvases read left to right. */
const NARROW_PX = 900

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
      <Handle id="t-top" isConnectable={false} position={Position.Top} type="target" />
      <Handle id="s-bottom" isConnectable={false} position={Position.Bottom} type="source" />
      <header>
        {data.order !== null && <b className="collab-order">{data.order}</b>}
        <span className="collab-mark"><Icon aria-hidden="true" size={13} /></span>
        <span>{data.label}</span>
        {data.live && <span className="collab-live" data-state={data.live} title={LIVE_TITLE[data.live]} />}
      </header>
      {data.sub && <p>{data.sub}</p>}
    </div>
  )
}

/** What was said, as a card of its own in the vertical flow; lines enter and leave on every side. */
function SaidNode({ data }: NodeProps<FlowNode>) {
  const said = data.said
  if (!said) return null
  return (
    <div className="collab-said" data-kind={said.kind} data-node="true" data-running={said.running ? 'true' : 'false'}>
      <Handle id="t-top" isConnectable={false} position={Position.Top} type="target" />
      <Handle id="s-bottom" isConnectable={false} position={Position.Bottom} type="source" />
      <Handle id="t-left" isConnectable={false} position={Position.Left} type="target" />
      <Handle id="s-left" isConnectable={false} position={Position.Left} type="source" />
      <Handle id="t-right" isConnectable={false} position={Position.Right} type="target" />
      <Handle id="s-right" isConnectable={false} position={Position.Right} type="source" />
      <small>{said.caption}</small>
      {said.text ? <p>{said.text}</p> : null}
    </div>
  )
}

const nodeTypes: NodeTypes = { agent: AgentNode, said: SaidNode }

type SaidEdgeData = { said: string; caption: string; kind: 'request' | 'response'; running: boolean }
type SaidEdge = Edge<SaidEdgeData, 'said'>

/** A request or answer as a card on its line: what was said, and under it which call and how many times. */
function SaidEdgeView({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd }: EdgeProps<SaidEdge>) {
  const [path, labelX, labelY] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 10 })
  return (
    <>
      <BaseEdge id={id} markerEnd={markerEnd} path={path} />
      {data && (
        <EdgeLabelRenderer>
          <div className="collab-said nodrag nopan" data-kind={data.kind} data-running={data.running ? 'true' : 'false'} style={{ transform: `translate(-50%, ${data.kind === 'request' ? '-100%' : '0%'}) translate(${labelX}px, ${labelY + (data.kind === 'request' ? -6 : 6)}px)` }}>
            <small>{data.caption}</small>
            {data.said ? <p>{data.said}</p> : null}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

const edgeTypes: EdgeTypes = { said: SaidEdgeView }

/** Refits the view to the flow that ran (the waiting agents stay below, reachable by scrolling) when the cards are laid out again, never on a plain selection. */
function Refit({ when, compact, bounds }: { when: unknown; compact: boolean; bounds: Rect | null }) {
  const { fitView, fitBounds } = useReactFlow()
  useEffect(() => {
    const timer = window.setTimeout(() => { void (bounds ? fitBounds(bounds, { padding: compact ? 0.25 : 0.12, duration: 250 }) : fitView({ padding: compact ? 0.25 : 0.1, duration: 250 })) }, 150)
    return () => window.clearTimeout(timer)
  }, [when, compact, bounds])
  return null
}

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
  // The canvas's own width decides the orientation: a narrow panel stacks the flow, a wide one reads left to right.
  const host = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState<number | null>(null)
  useEffect(() => {
    const element = host.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => { for (const entry of entries) setWidth(Math.round(entry.contentRect.width)) })
    observer.observe(element)
    return () => observer.disconnect()
  })
  const vertical = width !== null && width < NARROW_PX
  const graph = useMemo(() => {
    const spoken = new Set(messages.flatMap((message) => [message.from, message.to]))
    return buildGraph(messages, null, {
      live, orientation: vertical ? 'vertical' : 'horizontal',
      ...(compact ? { catalog: [...spoken].filter((id) => id !== ORCHESTRATOR && id !== USER).map((id) => catalog?.find((entry) => entry.id === id) ?? { id }) } : catalog ? { catalog } : {}),
    })
  }, [messages, catalog, live, compact, vertical])

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([])
  const selectedRef = useRef(selected)
  selectedRef.current = selected
  // A new record or catalog lays the cards out again (keeping the current selection); a selection only restyles them, so a dragged card stays put.
  useEffect(() => {
    setNodes(graph.nodes.map((node) => ({
      id: node.id, type: node.kind === 'said' ? 'said' : 'agent', position: node.position, draggable: node.kind !== 'said',
      data: { label: node.label, sub: node.sub, kind: node.kind, order: node.order, selected: node.id === selectedRef.current, idle: node.idle, live: node.live, agent: node.id, said: node.said },
    })))
  }, [graph, setNodes])
  useEffect(() => {
    setNodes((current) => current.map((node) => (node.data.selected === (node.id === selected) ? node : { ...node, data: { ...node.data, selected: node.id === selected } })))
  }, [selected, setNodes])

  const edges = useMemo<Edge[]>(() => graph.edges.map((edge) => {
    const spoken = edge.kind === 'request' || edge.kind === 'response'
    const back = edge.kind === 'response'
    const className = `collab-edge-${edge.kind}${edge.known ? '' : ' collab-edge-unknown'}${edge.running ? ' collab-edge-running' : ''}`
    if (edge.lane) {
      // The vertical flow: cards are nodes, so a line only needs the right handles for its lane.
      const isCard = (id: string) => id.startsWith('said:')
      const sourceHandle = edge.lane === 'down' ? 's-bottom' : isCard(edge.source) ? `s-${edge.lane}` : edge.lane === 'left' ? 'back' : 'out'
      const targetHandle = edge.lane === 'down' ? 't-top' : isCard(edge.target) ? `t-${edge.lane}` : edge.lane === 'left' ? 'in' : 'return'
      return {
        id: edge.id, source: edge.source, target: edge.target, sourceHandle, targetHandle, type: 'smoothstep', pathOptions: { borderRadius: 12, offset: 28 }, animated: !!edge.running, className,
        ...(spoken ? { markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: back ? 'var(--success)' : 'var(--accent)' } } : {}),
      }
    }
    const base = {
      id: edge.id, source: edge.source, target: edge.target,
      sourceHandle: back ? 'back' : 'out', targetHandle: back ? 'return' : 'in',
      animated: !!edge.running, className,
    }
    if (!spoken) return { ...base, label: edge.label || undefined, type: 'smoothstep', pathOptions: { borderRadius: 10 } }
    // What was said rides on the line as a card; the call and its count sit under it.
    return {
      ...base, type: 'said', data: { said: edge.said, caption: edge.caption ?? edge.label, kind: edge.kind, running: !!edge.running },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: back ? 'var(--success)' : 'var(--accent)' },
    }
  }), [graph])

  const order = useMemo(() => graph.nodes.filter((node) => node.order !== null).sort((a, b) => (a.order ?? 0) - (b.order ?? 0)).map((node) => node.label), [graph])
  // The flow that ran, with room above and below the cards for what was said; the waiting agents stay below, reachable by scrolling.
  const bounds = useMemo<Rect | null>(() => {
    const active = graph.nodes.filter((node) => !node.idle)
    if (!active.length) return null
    const right = (node: GraphNode) => node.position.x + (node.kind === 'said' ? CARD_WIDTH : NODE_WIDTH)
    const bottom = (node: GraphNode) => node.position.y + (node.kind === 'said' ? CARD_HEIGHT : NODE_HEIGHT)
    const x = Math.min(...active.map((node) => node.position.x)) - (vertical ? 40 : 0)
    const y = Math.min(...active.map((node) => node.position.y)) - (vertical ? 10 : 80)
    return { x, y, width: Math.max(...active.map(right)) + (vertical ? 40 : 0) - x, height: Math.max(...active.map(bottom)) + (vertical ? 10 : 90) - y }
  }, [graph, vertical])
  // A stacked flow gets the height it needs (within reason), so it reads at full size without zooming.
  const height = vertical && bounds && !compact ? Math.min(1100, Math.max(420, Math.round(bounds.height + 60))) : undefined

  if (!graph.nodes.length) {
    return (
      <div className="collab-graph collab-empty" data-compact={compact ? 'true' : 'false'} ref={host}>
        <MessagesSquare aria-hidden="true" size={22} />
        <span>아직 주고받은 요청·응답이 없어요</span>
      </div>
    )
  }
  return (
    <div className="collab-graph" data-compact={compact ? 'true' : 'false'} data-edge-count={edges.length} data-node-count={nodes.length} data-orientation={vertical ? 'vertical' : 'horizontal'} ref={host} style={height ? { blockSize: height } : undefined}>
      <ReactFlowProvider>
        <ReactFlow
          edgeTypes={edgeTypes}
          edges={edges}
          elementsSelectable
          onInit={(instance) => { void (bounds ? instance.fitBounds(bounds, { padding: compact ? 0.25 : 0.12 }) : instance.fitView({ padding: compact ? 0.25 : 0.1 })) }}
          maxZoom={1.2}
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
          <Refit bounds={bounds} compact={compact} when={graph} />
        </ReactFlow>
      </ReactFlowProvider>
      {!compact && <p className="collab-pattern">진행 순서 · {[agentLabel(ORCHESTRATOR), ...order].join(' → ')}</p>}
    </div>
  )
}
