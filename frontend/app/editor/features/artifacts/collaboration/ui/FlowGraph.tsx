'use client'

import '@xyflow/react/dist/style.css'
import { Background, BackgroundVariant, Controls, type Edge, Handle, MarkerType, type Node, type NodeProps, type NodeTypes, Position, ReactFlow, ReactFlowProvider, type Rect, useNodesState, useReactFlow } from '@xyflow/react'
import { MessagesSquare } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { markOf, ORCHESTRATOR, USER } from '@/lib/agents'
import { agentLabel } from '@/lib/orchestrator-runs/labels'

import type { CatalogEntry, LiveState } from '../lib/catalog'
import { buildGraph, CARD_HEIGHT, CARD_WIDTH, callWaves, type GraphNode, NODE_HEIGHT, NODE_WIDTH, partyOf, wavesLabel } from '../lib/graph'
import { patternLinks, patternNodes, patternOf } from '../lib/pattern'
import type { CollaborationMessage } from '../lib/transcript'
import { phaseLabel, protocolLabel, stepDone, stepStatus, type Workflow } from '@/lib/design-conversation/workflow'
import { SaidViewer } from './SaidViewer'
import './collaboration.css'

type FlowNodeData = Pick<GraphNode, 'label' | 'sub' | 'kind' | 'order' | 'selected' | 'idle' | 'live' | 'said' | 'items'> & { agent: string; workflowStatus?: string }
type FlowNode = Node<FlowNodeData, 'agent' | 'said'>

/** Below this width the flow stacks into one column; wider canvases read left to right. */
const NARROW_PX = 900

const LIVE_TITLE: Record<LiveState, string> = { up: '지금 응답함', down: '꺼져 있음', unknown: '상태 미확인' }

/**
 * One participant: its mark, name and whether its service answers, then everything it sent or was sent, one message at a
 * time (‹ › and 전체 보기), or what it answers when it did not take part.
 * Everything flows left to right: requests, the person's message and the call order enter on the left upper handle
 * and leave on the right upper one; answers go back on the lower pair.
 */
function AgentNode({ data }: NodeProps<FlowNode>) {
  const Icon = markOf(data.agent).icon
  const [open, setOpen] = useState(false)
  return (
    <div className={`collab-node${open ? ' nowheel' : ''}`} data-open={open ? 'true' : 'false'} data-hub={data.kind === 'hub' ? 'true' : 'false'} data-idle={data.idle ? 'true' : 'false'} data-kind={data.kind} data-selected={data.selected ? 'true' : 'false'}>
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
        {data.workflowStatus && <small>{data.workflowStatus}</small>}
        {data.live && <span className="collab-live" data-state={data.live} title={LIVE_TITLE[data.live]} />}
      </header>
      {data.items.length ? <SaidViewer items={data.items} onToggle={() => setOpen((value) => !value)} open={open} /> : data.sub ? <p>{data.sub}</p> : null}
    </div>
  )
}

/** What was said on one line, as a card of its own: every message on it, stepped through with ‹ ›; lines enter and leave on every side. */
function SaidNode({ data }: NodeProps<FlowNode>) {
  const said = data.said
  const [open, setOpen] = useState(false)
  if (!said) return null
  return (
    <div
      className={`collab-said${open ? ' nowheel' : ''}`}
      data-known={said.known ? 'true' : 'false'}
      data-kind={said.kind}
      data-node="true"
      data-open={open ? 'true' : 'false'}
      data-running={said.running ? 'true' : 'false'}
    >
      <Handle id="t-top" isConnectable={false} position={Position.Top} type="target" />
      <Handle id="s-bottom" isConnectable={false} position={Position.Bottom} type="source" />
      <Handle id="t-left" isConnectable={false} position={Position.Left} type="target" />
      <Handle id="s-left" isConnectable={false} position={Position.Left} type="source" />
      <Handle id="t-right" isConnectable={false} position={Position.Right} type="target" />
      <Handle id="s-right" isConnectable={false} position={Position.Right} type="source" />
      <SaidViewer items={said.items} onToggle={() => setOpen((value) => !value)} open={open} />
    </div>
  )
}

const nodeTypes: NodeTypes = { agent: AgentNode, said: SaidNode }

/**
 * Refits the view to the flow that ran (the waiting agents stay below, reachable by scrolling) when a card is added or
 * removed — never on a live update of the same cards, and never again once the user has zoomed or panned (the fit
 * button brings it back).
 */
function Refit({ when, compact, bounds, size, held }: { when: string; compact: boolean; bounds: Rect | null; size: number | undefined; held: { current: boolean } }) {
  const { fitView, fitBounds } = useReactFlow()
  // biome-ignore lint/correctness/useExhaustiveDependencies: bounds follow the cards; refitting on each live update is what this avoids.
  useEffect(() => {
    if (held.current) return
    const timer = window.setTimeout(() => { void (bounds ? fitBounds(bounds, { padding: compact ? 0.25 : 0.12, duration: 250 }) : fitView({ padding: compact ? 0.25 : 0.1, duration: 250 })) }, 150)
    return () => window.clearTimeout(timer)
  }, [when, compact, size])
  return null
}

interface Props {
  workflow?: Workflow
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
export default function FlowGraph({ messages, selected = null, onSelect, catalog, live, compact = false, workflow }: Props) {
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
  // 에이전트: who talked to whom (every agent of the network on the canvas). 패턴: the steps this turn ran, in the
  // order and at the same time they ran — the declared workflow when there is one, else the calls as the ledger timed them.
  const [view, setView] = useState<'agents' | 'pattern'>('agents')
  const pattern = useMemo(() => patternOf(messages, workflow), [messages, workflow])
  const names = useMemo(() => Object.fromEntries((catalog ?? []).filter((entry) => entry.label).map((entry) => [entry.id, entry.label!])), [catalog])
  const graph = useMemo(() => {
    if (view === 'pattern' && !compact) return { nodes: patternNodes(pattern, names), edges: [] }
    const spoken = new Set(messages.flatMap((message) => [message.from, message.to]))
    return buildGraph(messages, null, {
      live, orientation: vertical ? 'vertical' : 'horizontal',
      ...(compact ? { catalog: [...spoken].filter((id) => id !== ORCHESTRATOR && id !== USER).map((id) => catalog?.find((entry) => entry.id === id) ?? { id }) } : catalog ? { catalog } : {}),
    })
  }, [messages, catalog, live, compact, vertical, view, pattern, names])

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([])
  const selectedRef = useRef(selected)
  selectedRef.current = selected
  // Cards the user dragged keep where they were dropped.
  const moved = useRef(new Set<string>())
  // A live update replaces only the cards whose content changed: a fresh node is hidden until it is measured again,
  // so replacing every node on each update made cards flicker away under the pointer (clicks fell on the pane,
  // drags snapped back). A selection only restyles them.
  useEffect(() => {
    setNodes((current) => {
      // A card gone means another flow (another conversation or run): what was dragged there no longer applies.
      const ids = new Set(graph.nodes.map((node) => node.id))
      if (current.some((node) => !ids.has(node.id))) moved.current.clear()
      const known = new Map(current.map((node) => [node.id, node]))
      return graph.nodes.map((node) => {
        const agent = node.agent ?? node.id
        const data: FlowNodeData = { label: node.label, sub: node.sub, kind: node.kind, order: node.order, selected: agent === selectedRef.current, idle: node.idle, live: node.live, agent, said: node.said, items: node.items }
        const steps = node.agent ? [] : Object.values(workflow?.steps ?? {}).filter(step => step.owner === node.id)
        // An owner with several steps shows the one furthest from done: running, then waiting, then any trouble.
        if (steps.length) data.workflowStatus = stepStatus((['running', 'pending', 'failed', 'blocked', 'needs_revision', 'needs_evidence'].find(status => steps.some(step => step.status === status && !stepDone(step))) ?? 'succeeded')).label
        const old = known.get(node.id)
        const position = old && moved.current.has(node.id) ? old.position : node.position
        if (old && old.position.x === position.x && old.position.y === position.y && JSON.stringify(old.data) === JSON.stringify(data)) return old
        return { ...old, id: node.id, type: node.kind === 'said' ? 'said' : 'agent', position, draggable: true, data }
      })
    })
  }, [graph, setNodes, workflow])
  useEffect(() => {
    setNodes((current) => current.map((node) => (node.data.selected === (node.data.agent === selected) ? node : { ...node, data: { ...node.data, selected: node.data.agent === selected } })))
  }, [selected, setNodes])

  const communicationEdges = useMemo<Edge[]>(() => graph.edges.map((edge) => {
    const spoken = edge.kind === 'request' || edge.kind === 'response'
    const back = edge.kind === 'response'
    const className = `collab-edge-${edge.kind}${edge.known ? '' : ' collab-edge-unknown'}${edge.running ? ' collab-edge-running' : ''}`
    if (edge.sourceHandle && edge.targetHandle) {
      // The wide flow: each line names the handles it leaves and enters by.
      return {
        id: edge.id, source: edge.source, target: edge.target, sourceHandle: edge.sourceHandle, targetHandle: edge.targetHandle, type: 'smoothstep', pathOptions: { borderRadius: 12, offset: 18 }, animated: spoken, className,
        ...(spoken ? { markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: back ? 'var(--success)' : 'var(--accent)' } } : {}),
      }
    }
    if (edge.lane) {
      // The vertical flow: cards are nodes, so a line only needs the right handles for its lane.
      const isCard = (id: string) => id.startsWith('said:')
      const sourceHandle = edge.lane === 'down' ? 's-bottom' : isCard(edge.source) ? `s-${edge.lane}` : edge.lane === 'left' ? 'back' : 'out'
      const targetHandle = edge.lane === 'down' ? 't-top' : isCard(edge.target) ? `t-${edge.lane}` : edge.lane === 'left' ? 'in' : 'return'
      return {
        id: edge.id, source: edge.source, target: edge.target, sourceHandle, targetHandle, type: 'smoothstep', pathOptions: { borderRadius: 12, offset: 28 }, animated: spoken, className,
        ...(spoken ? { markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: back ? 'var(--success)' : 'var(--accent)' } } : {}),
      }
    }
    const base = {
      id: edge.id, source: edge.source, target: edge.target,
      sourceHandle: back ? 'back' : 'out', targetHandle: back ? 'return' : 'in',
      animated: spoken, className,
    }
    if (!spoken) return { ...base, label: edge.label || undefined, type: 'smoothstep', pathOptions: { borderRadius: 10 } }
    // What was said rides on the line as a card; the call and its count sit under it.
    return {
      ...base, type: 'said', data: { said: edge.said, caption: edge.caption ?? edge.label, kind: edge.kind, running: !!edge.running },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: back ? 'var(--success)' : 'var(--accent)' },
    }
  }), [graph])
  // A workflow's dependencies drawn between owners: one line per pair of owners (several steps share it, their
  // phases joined on the label); a step that depends on the same owner's earlier step is that owner's own business.
  const edges = useMemo<Edge[]>(() => {
    if (view === 'pattern' && !compact) {
      // The pattern's lines: each one leads from a finished (or running) step to the step that waited for it.
      return patternLinks(pattern).map((link) => ({
        id: `pattern:${link.id}`, source: link.source, target: link.target, sourceHandle: 'out', targetHandle: 'in', type: 'smoothstep', pathOptions: { borderRadius: 12 },
        animated: link.running, className: `collab-edge-pattern${link.running ? ' collab-edge-running' : ''}${link.done ? ' collab-edge-done' : ''}`,
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: link.done ? 'var(--success)' : 'var(--accent)' },
      }))
    }
    const pairs = new Map<string, { source: string; target: string; labels: string[]; running: boolean }>()
    for (const edge of workflow?.edges ?? []) {
      const from = workflow!.steps[edge.source]!, to = workflow!.steps[edge.target]!
      if (from.owner === to.owner || !graph.nodes.some(node => node.id === from.owner) || !graph.nodes.some(node => node.id === to.owner)) continue
      const key = `${from.owner}>${to.owner}`
      const pair = pairs.get(key) ?? { source: from.owner, target: to.owner, labels: [], running: false }
      const label = `${phaseLabel(from.phase)} → ${phaseLabel(to.phase)}`
      if (!pair.labels.includes(label)) pair.labels.push(label)
      pair.running ||= to.status === 'running'
      pairs.set(key, pair)
    }
    return [...communicationEdges, ...[...pairs.entries()].map(([key, pair]) => ({
      id: `workflow:${workflow!.id}:${key}`, source: pair.source, target: pair.target, sourceHandle: 's-bottom', targetHandle: 't-top', type: 'smoothstep',
      label: pair.labels.join(' · '), animated: pair.running, className: 'collab-edge-next', markerEnd: { type: MarkerType.ArrowClosed },
    }))]
  }, [communicationEdges, workflow, graph, view, compact, pattern])

  // A line runs to and from a card: clicking it, like clicking the card, picks the agent the card is about.
  const partyAt = (source: string, target: string) =>
    [source, target].map((id) => nodes.find((node) => node.id === id)?.data.said?.party).find(Boolean) ?? partyOf(source, target)
  const order = useMemo(() => graph.nodes.filter((node) => node.order !== null).sort((a, b) => (a.order ?? 0) - (b.order ?? 0)).map((node) => node.label), [graph])
  // How the calls actually ran, from the ledger's times: same-time calls as one wave, waves in order. A declared
  // workflow names its pattern instead; without one this is the turn's pattern as it happened.
  const waves = useMemo(() => (workflow ? [] : callWaves(messages)), [messages, workflow])
  const parallel = waves.filter((wave) => wave.length > 1).length
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
  // Which cards there are, not what they say: a new card refits the view, a live update of one does not.
  const layoutKey = graph.nodes.map((node) => node.id).join('|')
  const userMoved = useRef(false)
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
    <div className="collab-graph" data-workflow-id={workflow?.id} data-workflow-revision={workflow?.revision} data-protocol={workflow?.protocol} data-compact={compact ? 'true' : 'false'} data-edge-count={edges.length} data-node-count={nodes.length} data-orientation={vertical ? 'vertical' : 'horizontal'} ref={host} style={height ? { blockSize: height } : undefined}>
      <ReactFlowProvider>
        <ReactFlow
          edges={edges}
          elementsSelectable
          onInit={(instance) => { void (bounds ? instance.fitBounds(bounds, { padding: compact ? 0.25 : 0.12 }) : instance.fitView({ padding: compact ? 0.25 : 0.1 })) }}
          maxZoom={1.2}
          minZoom={0.25}
          nodeTypes={nodeTypes}
          nodes={nodes}
          nodesConnectable={false}
          nodesDraggable
          onEdgeClick={(_, edge) => onSelect?.(partyAt(edge.source, edge.target))}
          onNodeClick={(_, node) => { const party = node.data.said?.party ?? node.data.agent; onSelect?.(selected === party ? null : party) }}
          onNodeDragStop={(_, node) => { moved.current.add(node.id) }}
          onNodesChange={onNodesChange}
          onPaneClick={() => onSelect?.(null)}
          onMoveStart={(event) => { if (event) userMoved.current = true }}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} size={1} variant={BackgroundVariant.Dots} />
          <Controls position="bottom-left" showInteractive={false} />
          <Refit bounds={bounds} compact={compact} held={userMoved} size={height} when={layoutKey} />
        </ReactFlow>
      </ReactFlowProvider>
      {!compact && (
        <div className="collab-view" role="group" aria-label="보기">
          <button aria-pressed={view === 'agents'} onClick={() => setView('agents')} type="button">에이전트</button>
          <button aria-pressed={view === 'pattern'} onClick={() => setView('pattern')} type="button">패턴{pattern.steps.length ? ` ${Math.max(...pattern.steps.map((step) => step.column)) + 1}단계` : ''}</button>
        </div>
      )}
      {!compact && (
        <p className="collab-pattern">
          {workflow ? `함께 작업 · ${protocolLabel(workflow.protocol)} · ${[agentLabel(ORCHESTRATOR), ...order].join(' → ')}`
            : waves.length ? `진행 순서${parallel ? ` · 동시에 ${parallel}묶음` : ''} · ${wavesLabel(waves)}`
            : `진행 순서 · ${[agentLabel(ORCHESTRATOR), ...order].join(' → ')}`}
        </p>
      )}
    </div>
  )
}
