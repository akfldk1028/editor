/**
 * TerminationEditor - Editor for team termination conditions
 * Supports MaxMessage, TextMention, Timeout, StopMessage, and Or/And combinators
 */

import { Badge, Button, Input } from '@/elements/workspace/index'
import type { Component, TerminationConfig } from '@/lib/contracts/workspace'
import { ChevronDown, ChevronUp, Plus, X } from 'lucide-react'
import { memo, useCallback, useState } from 'react'

interface TerminationEditorProps {
  value: Component<TerminationConfig> | undefined
  onChange: (termination: Component<TerminationConfig> | undefined) => void
}

type TerminationType = 'max_messages' | 'text_mention' | 'timeout' | 'stop_message'

interface TerminationOption {
  type: TerminationType
  label: string
  provider: string
}

const TERMINATION_OPTIONS: TerminationOption[] = [
  {
    type: 'max_messages',
    label: 'Max Messages',
    provider: 'autogen_agentchat.conditions.MaxMessageTermination',
  },
  {
    type: 'text_mention',
    label: 'Text Mention',
    provider: 'autogen_agentchat.conditions.TextMentionTermination',
  },
  {
    type: 'timeout',
    label: 'Timeout',
    provider: 'autogen_agentchat.conditions.TimeoutTermination',
  },
  {
    type: 'stop_message',
    label: 'Stop Message',
    provider: 'autogen_agentchat.conditions.StopMessageTermination',
  },
]

function detectTerminationType(
  comp: Component<TerminationConfig>,
): TerminationType | 'or' | 'unknown' {
  const p = comp.provider ?? ''
  if (p.includes('MaxMessage')) return 'max_messages'
  if (p.includes('TextMention')) return 'text_mention'
  if (p.includes('Timeout')) return 'timeout'
  if (p.includes('StopMessage')) return 'stop_message'
  if (p.includes('OrTermination')) return 'or'
  return 'unknown'
}

function getConditions(comp: Component<TerminationConfig>): Component<TerminationConfig>[] {
  const config = comp.config as Record<string, unknown>
  if (config?.conditions && Array.isArray(config.conditions)) {
    return config.conditions as Component<TerminationConfig>[]
  }
  return [comp]
}

function buildCondition(type: TerminationType): Component<TerminationConfig> {
  const opt = TERMINATION_OPTIONS.find((o) => o.type === type)
  if (!opt) throw new Error(`Unknown termination type: ${type}`)

  const config: Record<string, unknown> = {}
  switch (type) {
    case 'max_messages':
      config.max_messages = 10
      break
    case 'text_mention':
      config.text = 'TERMINATE'
      break
    case 'timeout':
      config.timeout_seconds = 120
      break
    case 'stop_message':
      break
  }

  return {
    provider: opt.provider,
    component_type: 'termination',
    config: config as TerminationConfig,
  }
}

function combineConditions(
  conditions: Component<TerminationConfig>[],
  previous?: Component<TerminationConfig>,
): Component<TerminationConfig> {
  if (previous && /(?:And|Or)Termination$/.test(previous.provider)) {
    return { ...previous, config: { ...previous.config, conditions } as TerminationConfig }
  }
  if (conditions.length === 1 && conditions[0]) return conditions[0]
  return {
    provider: 'autogen_agentchat.conditions.OrTermination',
    component_type: 'termination',
    config: { conditions } as TerminationConfig,
  }
}

export const TerminationEditor = memo(function TerminationEditor({
  value,
  onChange,
}: TerminationEditorProps) {
  const [expanded, setExpanded] = useState(false)
  const [addType, setAddType] = useState<TerminationType>('max_messages')

  const conditions = value ? getConditions(value) : []

  const handleRemoveCondition = useCallback(
    (index: number) => {
      const updated = conditions.filter((_, i) => i !== index)
      onChange(updated.length > 0 ? combineConditions(updated, value) : undefined)
    },
    [conditions, onChange, value],
  )

  const handleAddCondition = useCallback(() => {
    const newCondition = buildCondition(addType)
    const updated = [...conditions, newCondition]
    onChange(combineConditions(updated, value))
  }, [addType, conditions, onChange, value])

  const handleUpdateConditionConfig = useCallback(
    (index: number, key: string, val: string | number) => {
      const updated = conditions.map((c, i) => {
        if (i !== index) return c
        return { ...c, config: { ...c.config, [key]: val } as TerminationConfig }
      })
      onChange(combineConditions(updated, value))
    },
    [conditions, onChange, value],
  )

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setExpanded((p) => !p)}
        className="flex items-center gap-1 text-sm font-medium text-(--color-text-secondary) hover:text-(--color-text-primary) transition-colors"
      >
        Termination Conditions
        <span className="ml-1">
          <Badge variant="default">{conditions.length}</Badge>
        </span>
        {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>

      {expanded && (
        <div className="space-y-2 pl-2 border-l-2 border-(--color-border-default)">
          {conditions.map((cond, i) => {
            const type = detectTerminationType(cond)
            const config = cond.config as Record<string, unknown>
            return (
              <div
                key={i}
                className="flex items-center gap-2 p-2 rounded bg-(--color-background-secondary)"
              >
                <Badge variant="default">{type}</Badge>
                {type === 'max_messages' && (
                  <Input
                    className="w-20"
                    type="number"
                    value={String(config.max_messages ?? 10)}
                    onChange={(e) =>
                      handleUpdateConditionConfig(i, 'max_messages', Number(e.target.value))
                    }
                    aria-label="Max messages"
                  />
                )}
                {type === 'text_mention' && (
                  <Input
                    className="flex-1"
                    value={String(config.text ?? 'TERMINATE')}
                    onChange={(e) => handleUpdateConditionConfig(i, 'text', e.target.value)}
                    aria-label="Termination text"
                  />
                )}
                {type === 'timeout' && (
                  <div className="flex items-center gap-1">
                    <Input
                      className="w-20"
                      type="number"
                      value={String(config.timeout_seconds ?? 120)}
                      onChange={(e) =>
                        handleUpdateConditionConfig(i, 'timeout_seconds', Number(e.target.value))
                      }
                      aria-label="Timeout seconds"
                    />
                    <span className="text-xs text-(--color-text-tertiary)">sec</span>
                  </div>
                )}
                {type === 'stop_message' && (
                  <span className="text-xs text-(--color-text-tertiary)">Stops on StopMessage</span>
                )}
                <button
                  type="button"
                  onClick={() => handleRemoveCondition(i)}
                  className="p-0.5 rounded hover:bg-(--color-background-primary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
                  aria-label="Remove condition"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            )
          })}

          <div className="flex items-center gap-2">
            <select
              value={addType}
              onChange={(e) => setAddType(e.target.value as TerminationType)}
              className="text-sm px-2 py-1 rounded border border-(--color-border-default) bg-(--color-background-primary) text-(--color-text-primary)"
              aria-label="Condition type to add"
            >
              {TERMINATION_OPTIONS.map((opt) => (
                <option key={opt.type} value={opt.type}>
                  {opt.label}
                </option>
              ))}
            </select>
            <Button size="sm" variant="ghost" onClick={handleAddCondition}>
              <Plus className="w-3.5 h-3.5 mr-1" />
              Add
            </Button>
          </div>
        </div>
      )}
    </div>
  )
})
