/**
 * AgentFlow - Main React Flow graph visualization for agent teams
 * Ported from AutoGen Studio agentflow.tsx
 *
 * Shows agent collaboration patterns as interactive graphs:
 * - Sequential (chain), Selector (hub-spoke), Handoff (mesh),
 *   Debate (ring), Reflection (chain+loop)
 */

import {
  applyNodeChanges,
  Background,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Node,
  type NodeChange,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import Dagre from 'dagre'
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from 'react'

import { AgentFlowToolbar, DEFAULT_SETTINGS, type FlowSettings } from './AgentFlowToolbar'
import AgentNode from './AgentNode'
import { CustomEdge } from './CustomEdge'
import { generateLayoutFromPattern } from './layout-generator'
import {
  NODE_DIMENSIONS,
  PATTERN_DEFINITIONS,
  type CustomEdge as CustomEdgeType,
  type Participant,
  type PatternType,
} from './types'

export interface AgentFlowProps {
  /** Team provider string (e.g. "RoundRobinGroupChat", "SelectorGroupChat", "Swarm") */
  teamProvider?: string
  /** List of agent participants */
  participants: Participant[]
  /** Optional pattern type override */
  patternType?: PatternType
  /** Height of the graph container */
  height?: number | string
  /** Callback when an agent node is clicked (receives agent label) */
  onNodeClick?: (agentName: string) => void
  /** Callback when an agent node is double-clicked (receives agent label) */
  onNodeDoubleClick?: (agentName: string) => void
  /** Active agent names for live execution visualization */
  activeAgents?: Set<string>
  /** Whether execution is in progress */
  isProcessing?: boolean
  /** Whether execution is complete */
  isComplete?: boolean
  /** Run status for end node */
  runStatus?: string
  /** Reason text for end node (e.g. which agent terminated) */
  runReason?: string
  /** Map of agent name -> last message (truncated) for live display */
  agentMessages?: Map<string, string>
}

// --- Dagre Layout (for chain/sequential + execution flow) ---

function getLayoutedElements(nodes: Node[], edges: CustomEdgeType[], direction: 'TB' | 'LR') {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  g.setGraph({
    rankdir: direction,
    nodesep: 110,
    ranksep: 100,
    ranker: 'network-simplex',
    marginx: 30,
    marginy: 30,
  })

  nodes.forEach((node) => {
    const dim = node.data.type === 'end' ? NODE_DIMENSIONS.end : NODE_DIMENSIONS.default
    g.setNode(node.id, { ...node, ...dim })
  })

  edges.forEach((edge) => {
    g.setEdge(edge.source, edge.target, { weight: 1, minlen: 1 })
  })

  Dagre.layout(g)

  return {
    nodes: nodes.map((node) => {
      const { x, y } = g.node(node.id)
      const dim = node.data.type === 'end' ? NODE_DIMENSIONS.end : NODE_DIMENSIONS.default
      return { ...node, position: { x: x - dim.width / 2, y: y - dim.height / 2 } }
    }),
    edges,
  }
}

// --- Pattern Detection ---

function detectPatternType(provider?: string, participants?: Participant[]): PatternType {
  if (!provider) return 'unknown'
  const p = provider.toLowerCase()

  if (p.includes('swarm')) return 'handoff'

  if (p.includes('selector')) {
    const names = (participants ?? []).map((a) => (a.config?.name ?? '').toLowerCase())
    if (names.some((n) => n.includes('advocate') || n.includes('judge') || n.includes('critic'))) {
      return 'debate'
    }
    return 'selector'
  }

  if (p.includes('roundrobin')) {
    const names = (participants ?? []).map((a) => (a.config?.name ?? '').toLowerCase())
    if (
      (participants?.length ?? 0) === 2 &&
      names.some((n) => n.includes('generator') || n.includes('writer')) &&
      names.some((n) => n.includes('critic') || n.includes('reviewer'))
    ) {
      return 'reflection'
    }
    return 'sequential'
  }

  return 'unknown'
}

// --- Constants (stable references to avoid re-renders) ---

const nodeTypes: NodeTypes = { agentNode: AgentNode }
const edgeTypes = { custom: CustomEdge }
const PRO_OPTIONS = { hideAttribution: true } as const
const DEFAULT_VIEWPORT = { x: 0, y: 0, zoom: 1 } as const
const FIT_VIEW_OPTIONS = { padding: 0.2, duration: 200 } as const

// --- Inner Component (requires ReactFlowProvider) ---

const AgentFlowInner = memo(function AgentFlowInner({
  teamProvider,
  participants,
  patternType: overridePattern,
  height = 400,
  onNodeClick,
  onNodeDoubleClick,
  activeAgents: activeAgentsProp,
  isProcessing: isProcessingProp,
  isComplete: isCompleteProp,
  runStatus,
  runReason,
  agentMessages,
}: AgentFlowProps) {
  const { fitView } = useReactFlow()
  const [nodes, setNodes] = useState<Node[]>([])
  const [edges, setEdges] = useState<CustomEdgeType[]>([])
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [settings, setSettings] = useState<FlowSettings>(DEFAULT_SETTINGS)
  const flowWrapper = useRef<HTMLDivElement>(null)
  const fitViewTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((nds) => applyNodeChanges(changes, nds))
  }, [])

  const handleNodeClick = useCallback(
    (_event: ReactMouseEvent, node: Node) => {
      if (node.data.type === 'agent' && !node.data.isHub) {
        onNodeClick?.(node.data.label as string)
      }
    },
    [onNodeClick],
  )

  const handleNodeDoubleClick = useCallback(
    (_event: ReactMouseEvent, node: Node) => {
      if (node.data.type === 'agent' || node.data.type === 'user') {
        onNodeDoubleClick?.(node.data.label as string)
      }
    },
    [onNodeDoubleClick],
  )

  const patternType = useMemo(
    () => overridePattern ?? detectPatternType(teamProvider, participants),
    [overridePattern, teamProvider, participants],
  )

  // Heavy: regenerate layout only on structural changes
  useEffect(() => {
    const patternDef = PATTERN_DEFINITIONS[patternType] ?? PATTERN_DEFINITIONS.sequential!

    // Pass empty activeAgents - active state is managed by the light effect below
    const result = generateLayoutFromPattern(
      patternDef,
      participants,
      new Set<string>(),
      isProcessingProp ?? false,
      isCompleteProp ?? false,
      runStatus,
    )

    // Chain layout uses Dagre; others use custom positions
    if (patternDef.visual.layout === 'chain') {
      const { nodes: ln, edges: le } = getLayoutedElements(
        result.nodes,
        result.edges,
        settings.direction,
      )
      setNodes(ln)
      setEdges(le)
    } else {
      setNodes(result.nodes)
      setEdges(result.edges)
    }

    clearTimeout(fitViewTimerRef.current)
    fitViewTimerRef.current = setTimeout(() => fitView(FIT_VIEW_OPTIONS), 50)
    return () => clearTimeout(fitViewTimerRef.current)
  }, [
    patternType,
    participants,
    settings.direction,
    fitView,
    isProcessingProp,
    isCompleteProp,
    runStatus,
  ])

  // Light: update active state + messages + end reason without full layout rebuild
  useEffect(() => {
    setNodes((prev) => {
      if (prev.length === 0) return prev
      let changed = false
      const updated = prev.map((node) => {
        if (node.data.type === 'end') {
          if (node.data.reason !== (runReason ?? '')) {
            changed = true
            return { ...node, data: { ...node.data, reason: runReason ?? '' } }
          }
          return node
        }
        const label = node.data.label as string
        const isActive = activeAgentsProp?.has(label) ?? false
        const msg = agentMessages?.get(label)
        if (node.data.isActive !== isActive || node.data.lastMessage !== msg) {
          changed = true
          return { ...node, data: { ...node.data, isActive, lastMessage: msg } }
        }
        return node
      })
      return changed ? updated : prev
    })
  }, [activeAgentsProp, agentMessages, runReason])

  // Fullscreen escape handler
  useEffect(() => {
    if (!isFullscreen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsFullscreen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [isFullscreen])

  // Refit view after fullscreen toggle
  useEffect(() => {
    const timerId = setTimeout(() => fitView(FIT_VIEW_OPTIONS), 100)
    return () => clearTimeout(timerId)
  }, [isFullscreen, fitView])

  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((prev) => !prev)
  }, [])

  const toolbarProps = useMemo(
    () => ({
      isFullscreen,
      onToggleFullscreen: toggleFullscreen,
      onResetView: () => fitView(FIT_VIEW_OPTIONS),
      settings,
      onSettingsChange: setSettings,
    }),
    [isFullscreen, toggleFullscreen, fitView, settings],
  )

  return (
    <div
      ref={flowWrapper}
      className={`transition-all duration-200 ${
        isFullscreen
          ? 'fixed inset-4 z-50 shadow-2xl'
          : 'w-full rounded-lg border border-(--color-border-default)'
      } bg-(--color-background-secondary)`}
      style={
        isFullscreen ? undefined : { height: typeof height === 'number' ? `${height}px` : height }
      }
    >
      {isFullscreen && (
        <div
          className="fixed inset-0 -z-10 bg-black/50 backdrop-blur-sm"
          aria-hidden="true"
          onClick={toggleFullscreen}
        />
      )}

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultViewport={DEFAULT_VIEWPORT}
        minZoom={0.3}
        maxZoom={2}
        onNodesChange={onNodesChange}
        onNodeClick={handleNodeClick}
        onNodeDoubleClick={handleNodeDoubleClick}
        proOptions={PRO_OPTIONS}
        fitView
      >
        {settings.showGrid && <Background />}
        {settings.showMiniMap && <MiniMap />}
        <AgentFlowToolbar {...toolbarProps} />
      </ReactFlow>
    </div>
  )
})

// --- Exported Wrapper ---

export default function AgentFlow(props: AgentFlowProps) {
  return (
    <ReactFlowProvider>
      <AgentFlowInner {...props} />
    </ReactFlowProvider>
  )
}

export { detectPatternType }
