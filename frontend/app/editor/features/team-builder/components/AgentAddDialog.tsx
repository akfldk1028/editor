/**
 * AgentAddDialog - Dialog for adding a new agent to a team
 * Offers assistant, web_surfer, and user_proxy presets
 */

import { Button, Card, Input } from '@/elements/workspace/index'
import type { AgentConfig, Component } from '@/lib/contracts/workspace'
import { Bot, Globe, Plus, User, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

interface AgentAddDialogProps {
  open: boolean
  onClose: () => void
  onAdd: (agent: Component<AgentConfig>) => void
}

type AgentPreset = 'assistant' | 'web_surfer' | 'user_proxy'

interface PresetInfo {
  type: AgentPreset
  label: string
  icon: typeof Bot
  provider: string
  description: string
}

const AGENT_PRESETS: PresetInfo[] = [
  {
    type: 'assistant',
    label: 'Assistant Agent',
    icon: Bot,
    provider: 'autogen_agentchat.agents.AssistantAgent',
    description: 'General-purpose LLM agent with tool use',
  },
  {
    type: 'web_surfer',
    label: 'Web Surfer',
    icon: Globe,
    provider: 'autogen_ext.agents.web_surfer.MultimodalWebSurfer',
    description: 'Browser-powered web research agent',
  },
  {
    type: 'user_proxy',
    label: 'User Proxy',
    icon: User,
    provider: 'autogen_agentchat.agents.UserProxyAgent',
    description: 'Represents a human in the conversation',
  },
]

function buildAgentComponent(preset: AgentPreset, name: string): Component<AgentConfig> {
  const info = AGENT_PRESETS.find((p) => p.type === preset)
  if (!info) throw new Error(`Unknown preset: ${preset}`)

  const base: Record<string, unknown> = { name }

  switch (preset) {
    case 'assistant':
      base.description = 'A helpful assistant agent'
      base.system_message = 'You are a helpful assistant.'
      base.reflect_on_tool_use = false
      base.tool_call_summary_format = '{result}'
      base.model_client_stream = false
      base.model_client = {
        provider: 'autogen_ext.models.openai.OpenAIChatCompletionClient',
        component_type: 'model',
        config: {
          model: 'gpt-4o',
          model_info: { vision: true, function_calling: true, json_output: true, family: 'openai' },
        },
      }
      break
    case 'web_surfer':
      base.description = 'A web browsing agent'
      base.model_client = {
        provider: 'autogen_ext.models.openai.OpenAIChatCompletionClient',
        component_type: 'model',
        config: {
          model: 'gpt-4o',
          model_info: { vision: true, function_calling: true, json_output: true, family: 'openai' },
        },
      }
      break
    case 'user_proxy':
      base.description = 'A human user proxy'
      break
  }

  return {
    provider: info.provider,
    component_type: 'agent',
    description: base.description as string,
    label: name,
    config: base as unknown as AgentConfig,
  }
}

export function AgentAddDialog({ open, onClose, onAdd }: AgentAddDialogProps) {
  const [selectedPreset, setSelectedPreset] = useState<AgentPreset>('assistant')
  const [name, setName] = useState('')

  useEffect(() => {
    if (open) {
      setSelectedPreset('assistant')
      setName('')
    }
  }, [open])

  const handleAdd = useCallback(() => {
    if (!name.trim()) return
    const agent = buildAgentComponent(selectedPreset, name.trim())
    onAdd(agent)
    onClose()
  }, [selectedPreset, name, onAdd, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label="Add agent to team"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <Card className="w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-heading-small">Add Agent</h2>
          <button
            onClick={onClose}
            aria-label="Close add agent dialog"
            className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label
              htmlFor="agent-add-name"
              className="text-sm font-medium text-(--color-text-secondary) mb-1 block"
            >
              Agent Name <span className="text-(--color-semantic-error)">*</span>
            </label>
            <Input
              id="agent-add-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my_agent"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && name.trim()) handleAdd()
              }}
            />
          </div>

          <div>
            <label className="text-sm font-medium text-(--color-text-secondary) mb-2 block">
              Agent Type
            </label>
            <div className="space-y-2" role="radiogroup" aria-label="Agent type selector">
              {AGENT_PRESETS.map((preset) => {
                const Icon = preset.icon
                const isSelected = selectedPreset === preset.type
                return (
                  <div
                    key={preset.type}
                    role="radio"
                    aria-checked={isSelected}
                    tabIndex={isSelected ? 0 : -1}
                    onClick={() => setSelectedPreset(preset.type)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelectedPreset(preset.type)
                      }
                    }}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                      isSelected
                        ? 'ring-2 ring-(--color-accent-primary) border-(--color-accent-primary) bg-(--color-background-secondary)'
                        : 'border-(--color-border-default) hover:border-(--color-accent-primary)'
                    }`}
                  >
                    <Icon className="w-5 h-5 text-(--color-text-secondary) flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{preset.label}</p>
                      <p className="text-xs text-(--color-text-tertiary)">{preset.description}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleAdd} disabled={!name.trim()}>
            <Plus className="w-4 h-4 mr-1.5" />
            Add Agent
          </Button>
        </div>
      </Card>
    </div>
  )
}
