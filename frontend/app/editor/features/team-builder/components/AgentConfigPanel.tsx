/**
 * AgentConfigPanel - Read-only agent configuration side panel
 * Shown when clicking an agent node in the AgentFlow graph
 */

import { Badge, Card } from '@/elements/workspace/index'
import type { AgentConfig, Component } from '@/lib/contracts/workspace'
import { ChevronDown, ChevronUp, X } from 'lucide-react'
import { memo, useState } from 'react'

interface AgentConfigPanelProps {
  agent: Component<AgentConfig>
  onClose: () => void
}

export const AgentConfigPanel = memo(function AgentConfigPanel({
  agent,
  onClose,
}: AgentConfigPanelProps) {
  const [showFullMessage, setShowFullMessage] = useState(false)
  // Cast once to loose record for dynamic property access
  const raw = agent.config as unknown as Record<string, unknown>
  const name = (raw.name as string) ?? 'Unknown'
  const description = (agent.description ?? raw.description) as string | undefined
  const systemMessage = raw.system_message as string | undefined
  const reflectOnToolUse = raw.reflect_on_tool_use as boolean | undefined
  const toolCallSummaryFormat = raw.tool_call_summary_format as string | undefined

  // Model client info
  const modelClient = raw.model_client as Component<Record<string, unknown>> | undefined
  const modelProvider = modelClient?.provider ?? ''
  const modelName = modelClient?.config?.model as string | undefined

  // Tools / workbench
  const workbench = raw.workbench
  const tools: string[] = []
  if (Array.isArray(workbench)) {
    for (const wb of workbench) {
      const wbComp = wb as Component<Record<string, unknown>>
      if (wbComp?.config && 'server_params' in wbComp.config) {
        tools.push(wbComp.label ?? 'MCP Tool')
      }
    }
  } else if (workbench && typeof workbench === 'object') {
    const wbComp = workbench as Component<Record<string, unknown>>
    tools.push(wbComp.label ?? 'MCP Tool')
  }

  // Handoffs
  const handoffs = raw.handoffs as unknown[] | undefined

  const messagePreview =
    systemMessage && systemMessage.length > 150
      ? systemMessage.slice(0, 150) + '../index'
      : systemMessage

  return (
    <Card
      className="relative h-full overflow-y-auto"
      role="complementary"
      aria-label="Agent configuration panel"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-heading-small truncate">{name}</h3>
          <Badge variant="default">{agent.provider?.split('../index').pop() ?? 'Agent'}</Badge>
        </div>
        <button
          onClick={onClose}
          aria-label="Close agent panel"
          className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary) flex-shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <span className="text-(--color-text-tertiary)">Name</span>
          <p className="font-medium">{name}</p>
        </div>
        <div>
          <span className="text-(--color-text-tertiary)">Provider</span>
          <p className="font-medium font-mono text-xs truncate">{agent.provider ?? 'N/A'}</p>
        </div>
        {description && (
          <div className="col-span-2">
            <span className="text-(--color-text-tertiary)">Description</span>
            <p className="font-medium">{description}</p>
          </div>
        )}
      </div>

      {/* System Message */}
      {systemMessage && (
        <div className="mt-4">
          <div className="flex items-center gap-1 mb-1">
            <span className="text-sm text-(--color-text-tertiary)">System Message</span>
            {systemMessage.length > 150 && (
              <button
                onClick={() => setShowFullMessage((p) => !p)}
                aria-expanded={showFullMessage}
                className="text-xs text-(--color-accent-primary) hover:underline flex items-center gap-0.5"
              >
                {showFullMessage ? 'Less' : 'More'}
                {showFullMessage ? (
                  <ChevronUp className="w-3 h-3" />
                ) : (
                  <ChevronDown className="w-3 h-3" />
                )}
              </button>
            )}
          </div>
          <pre className="text-xs font-mono whitespace-pre-wrap bg-(--color-background-secondary) p-2 rounded max-h-48 overflow-y-auto">
            {showFullMessage ? systemMessage : messagePreview}
          </pre>
        </div>
      )}

      {/* Model Client */}
      {modelClient && (
        <div className="mt-4">
          <span className="text-sm text-(--color-text-tertiary)">Model</span>
          <div className="flex items-center gap-2 mt-1">
            <Badge variant="primary">{modelName ?? 'unknown'}</Badge>
            <span className="text-xs text-(--color-text-tertiary) font-mono">
              {modelProvider.split('../index').pop()}
            </span>
          </div>
        </div>
      )}

      {/* Tools */}
      {tools.length > 0 && (
        <div className="mt-4">
          <span className="text-sm text-(--color-text-tertiary)">Tools</span>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {tools.map((t, i) => (
              <Badge key={i} variant="outline">
                {t}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Handoffs */}
      {handoffs && handoffs.length > 0 && (
        <div className="mt-4">
          <span className="text-sm text-(--color-text-tertiary)">Handoffs</span>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {handoffs.map((h, i) => {
              const target =
                typeof h === 'object' && h !== null && 'target' in h
                  ? String((h as Record<string, unknown>).target)
                  : typeof h === 'string'
                    ? h
                    : `handoff-${i}`
              return (
                <Badge key={i} variant="warning">
                  {target}
                </Badge>
              )
            })}
          </div>
        </div>
      )}

      {/* Config Flags */}
      {(reflectOnToolUse !== undefined || toolCallSummaryFormat !== undefined) && (
        <div className="mt-4 space-y-1">
          <span className="text-sm text-(--color-text-tertiary)">Config</span>
          {reflectOnToolUse !== undefined && (
            <p className="text-xs font-mono">reflect_on_tool_use: {String(reflectOnToolUse)}</p>
          )}
          {toolCallSummaryFormat !== undefined && (
            <p className="text-xs font-mono truncate" title={toolCallSummaryFormat}>
              tool_call_summary_format: {toolCallSummaryFormat}
            </p>
          )}
        </div>
      )}
    </Card>
  )
})
