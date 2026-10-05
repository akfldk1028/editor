import { memo } from 'react'
import { Badge } from '@/elements/workspace'
import { Wrench, Server, Trash2, RefreshCw, Terminal, Globe, Zap, ChevronRight, Loader2 } from 'lucide-react'
import type { McpServer, McpTool, McpServerStatus } from './mcpStore'

const STATUS_STYLES: Record<McpServerStatus, { dot: string; label: string }> = {
  connected: { dot: 'bg-(--color-semantic-success)', label: 'Connected' },
  connecting: { dot: 'bg-(--color-semantic-warning)', label: 'Connecting...' },
  disconnected: { dot: 'bg-(--color-text-tertiary)', label: 'Disconnected' },
  error: { dot: 'bg-(--color-semantic-error)', label: 'Error' },
}

const TYPE_ICONS: Record<string, typeof Terminal> = {
  stdio: Terminal,
  sse: Globe,
  streamable_http: Zap,
}

const TYPE_LABELS: Record<string, string> = {
  stdio: 'Stdio',
  sse: 'SSE',
  streamable_http: 'HTTP',
}

function ServerStatusDot({ status }: { status: McpServerStatus }) {
  const style = STATUS_STYLES[status]
  return (
    <span className="flex items-center gap-1.5" title={style.label}>
      <span className={`w-2 h-2 rounded-full ${style.dot}`} />
      <span className="text-xs text-(--color-text-tertiary)">{style.label}</span>
    </span>
  )
}

interface ServerCardProps {
  server: McpServer
  isSelected: boolean
  isConnecting: boolean
  onSelect: () => void
  onRemove: () => void
  onCheckHealth: () => void
}

export const ServerCard = memo(function ServerCard({ server, isSelected, isConnecting, onSelect, onRemove, onCheckHealth }: ServerCardProps) {
  const TypeIcon = TYPE_ICONS[server.type] ?? Server

  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect() } }}
      className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
        isSelected
          ? 'ring-2 ring-(--color-accent-primary) border-(--color-accent-primary) bg-(--color-background-secondary)'
          : 'border-(--color-border-default) hover:border-(--color-accent-primary)'
      }`}
    >
      <TypeIcon className="w-5 h-5 text-(--color-text-secondary) flex-shrink-0" />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium truncate">{server.name}</p>
          <span className="flex-shrink-0">
            <Badge variant="outline">{TYPE_LABELS[server.type]}</Badge>
          </span>
        </div>
        <div className="flex items-center gap-3 mt-1">
          <ServerStatusDot status={server.status} />
          {server.tools.length > 0 && (
            <span className="text-xs text-(--color-text-tertiary)">
              {server.tools.length} tool{server.tools.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1 flex-shrink-0">
        <button
          onClick={(e) => { e.stopPropagation(); onCheckHealth() }}
          disabled={isConnecting}
          aria-label={`Check health of ${server.name}`}
          title={server.status === 'connected' ? 'Disconnect' : 'Connect'}
          className="p-1.5 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) hover:text-(--color-text-primary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary) transition-colors disabled:opacity-50"
        >
          {isConnecting ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5" />
          )}
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onRemove() }}
          aria-label={`Remove ${server.name}`}
          title="Remove server"
          className="p-1.5 rounded hover:bg-(--color-semantic-error-light) text-(--color-text-tertiary) hover:text-(--color-semantic-error) focus:outline-none focus:ring-2 focus:ring-(--color-semantic-error) transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
})

interface ToolCardProps {
  tool: McpTool
  isSelected: boolean
  onSelect: () => void
}

export const ToolCard = memo(function ToolCard({ tool, isSelected, onSelect }: ToolCardProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect() } }}
      className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
        isSelected
          ? 'ring-2 ring-(--color-accent-primary) border-(--color-accent-primary) bg-(--color-background-secondary)'
          : 'border-(--color-border-default) hover:border-(--color-accent-primary)'
      }`}
    >
      <Wrench className="w-4 h-4 text-(--color-text-tertiary) flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium font-mono">{tool.name}</p>
        <p className="text-xs text-(--color-text-tertiary) truncate">{tool.description}</p>
      </div>
      <ChevronRight className="w-4 h-4 text-(--color-text-tertiary) flex-shrink-0" />
    </div>
  )
})

// --------------- Helpers ---------------

export function buildSchemaTemplate(schema: Record<string, unknown>): string {
  const properties = schema.properties as Record<string, Record<string, unknown>> | undefined
  if (!properties) return '{}'
  const template: Record<string, unknown> = {}
  for (const [key, prop] of Object.entries(properties)) {
    switch (prop.type) {
      case 'string': template[key] = ''; break
      case 'number': template[key] = 0; break
      case 'boolean': template[key] = false; break
      case 'array': template[key] = []; break
      case 'object': template[key] = {}; break
      default: template[key] = null
    }
  }
  return JSON.stringify(template, null, 2)
}
