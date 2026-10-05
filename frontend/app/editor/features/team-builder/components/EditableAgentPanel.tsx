/**
 * EditableAgentPanel - Editable agent configuration side panel
 * Shown in edit mode when clicking an agent node
 */

import { Badge, Button, Card, Input } from '@/elements/workspace/index'
import type { AgentConfig, Component, ModelConfig } from '@/lib/contracts/workspace'
import { Trash2, X } from 'lucide-react'
import { memo, useCallback, useEffect, useState } from 'react'
import { ModelSelector } from './ModelSelector'

interface EditableAgentPanelProps {
  agent: Component<AgentConfig>
  index: number
  onUpdate: (index: number, agent: Component<AgentConfig>) => void
  onRemove: (index: number) => void
  onClose: () => void
}

export const EditableAgentPanel = memo(function EditableAgentPanel({
  agent,
  index,
  onUpdate,
  onRemove,
  onClose,
}: EditableAgentPanelProps) {
  const [confirmRemove, setConfirmRemove] = useState(false)

  // C1 fix: Reset confirm state when agent changes
  useEffect(() => {
    setConfirmRemove(false)
  }, [agent])

  const raw = agent.config as unknown as Record<string, unknown>
  const name = (raw.name as string) ?? 'Unknown'
  const description = (agent.description ?? raw.description) as string | undefined
  const systemMessage = raw.system_message as string | undefined
  const modelClient = raw.model_client as Component<ModelConfig> | undefined

  const updateField = useCallback(
    (field: string, value: unknown) => {
      const updatedConfig = { ...raw, [field]: value }
      onUpdate(index, { ...agent, config: updatedConfig as unknown as AgentConfig })
    },
    [agent, raw, index, onUpdate],
  )

  const updateDescription = useCallback(
    (value: string) => {
      onUpdate(index, { ...agent, description: value || null })
    },
    [agent, index, onUpdate],
  )

  const handleModelChange = useCallback(
    (model: Component<ModelConfig>) => {
      updateField('model_client', model)
    },
    [updateField],
  )

  const handleRemove = useCallback(() => {
    if (!confirmRemove) {
      setConfirmRemove(true)
      return
    }
    onRemove(index)
    onClose()
  }, [confirmRemove, index, onRemove, onClose])

  return (
    <Card
      className="relative h-full overflow-y-auto"
      role="complementary"
      aria-label="Edit agent configuration"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-heading-small truncate">{name}</h3>
          <Badge variant="warning">Editing</Badge>
        </div>
        <button
          onClick={onClose}
          aria-label="Close agent editor"
          className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary) flex-shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-4">
        {/* Name */}
        <div>
          <label className="text-sm text-(--color-text-tertiary) mb-1 block">Name</label>
          <Input value={name} onChange={(e) => updateField('name', e.target.value)} />
        </div>

        {/* Description */}
        <div>
          <label className="text-sm text-(--color-text-tertiary) mb-1 block">Description</label>
          <Input
            value={description ?? ''}
            onChange={(e) => updateDescription(e.target.value)}
            placeholder="Agent description..."
          />
        </div>

        {/* System Message */}
        {agent.provider?.includes('AssistantAgent') && (
          <div>
            <label
              htmlFor="agent-system-message"
              className="text-sm text-(--color-text-tertiary) mb-1 block"
            >
              System Message
            </label>
            <textarea
              id="agent-system-message"
              className="w-full p-2 rounded border border-(--color-border-default) bg-(--color-background-primary) text-sm font-mono resize-y min-h-24 text-(--color-text-primary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
              value={systemMessage ?? ''}
              onChange={(e) => updateField('system_message', e.target.value)}
              rows={4}
            />
          </div>
        )}

        {/* Model Client */}
        {(agent.provider?.includes('AssistantAgent') || agent.provider?.includes('WebSurfer')) && (
          <div>
            <label className="text-sm text-(--color-text-tertiary) mb-1 block">Model</label>
            <ModelSelector value={modelClient} onChange={handleModelChange} />
          </div>
        )}

        {/* Config Flags */}
        {agent.provider?.includes('AssistantAgent') && (
          <div className="space-y-2">
            <label className="text-sm text-(--color-text-tertiary) block">Options</label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(raw.reflect_on_tool_use)}
                onChange={(e) => updateField('reflect_on_tool_use', e.target.checked)}
                className="rounded"
              />
              Reflect on tool use
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(raw.model_client_stream)}
                onChange={(e) => updateField('model_client_stream', e.target.checked)}
                className="rounded"
              />
              Stream model output
            </label>
          </div>
        )}

        {/* Provider (read-only) */}
        <div>
          <label className="text-sm text-(--color-text-tertiary) mb-1 block">Provider</label>
          <p className="text-xs font-mono text-(--color-text-secondary) bg-(--color-background-secondary) p-2 rounded truncate">
            {agent.provider ?? 'N/A'}
          </p>
        </div>

        {/* Remove Agent */}
        <div className="pt-2 border-t border-(--color-border-default)">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRemove}
            className="text-(--color-semantic-error) hover:bg-(--color-semantic-error)/10"
          >
            <Trash2 className="w-3.5 h-3.5 mr-1.5" />
            {confirmRemove ? 'Click again to confirm' : 'Remove Agent'}
          </Button>
        </div>
      </div>
    </Card>
  )
})
