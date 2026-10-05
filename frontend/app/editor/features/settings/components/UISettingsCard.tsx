import { Button, Card, Input, Toggle } from '@/elements/workspace'
import { Monitor } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useSettings, useUpdateSettings } from '../hooks/useSettings'
import { truncateError } from '@/lib/display-error'
import { useSettingsStore } from '../model/settings-store'
import type { Settings } from '../model/types'
export function UISettingsCard() {
  const { data: settings, isLoading, error } = useSettings()
  const updateSettings = useUpdateSettings()
  const store = useSettingsStore()
  const hydrate = useSettingsStore((s) => s.hydrate)

  // Track whether initial hydration happened
  const hydratedRef = useRef(false)

  // Hydrate store from API on first load
  useEffect(() => {
    if (settings?.config?.ui && !hydratedRef.current) {
      hydrate(settings.config.ui)
      hydratedRef.current = true
    }
  }, [settings, hydrate])

  // Dirty check: compare store values to API values
  const isDirty = useMemo(() => {
    if (!settings?.config?.ui) return false
    const ui = settings.config.ui
    return (
      store.showLlmEvents !== ui.show_llm_call_events ||
      store.expandMessages !== (ui.expanded_messages_by_default ?? false) ||
      store.showAgentFlow !== (ui.show_agent_flow_by_default ?? false) ||
      store.humanInputTimeout !== (ui.human_input_timeout_minutes ?? 3)
    )
  }, [
    settings,
    store.showLlmEvents,
    store.expandMessages,
    store.showAgentFlow,
    store.humanInputTimeout,
  ])

  const handleSave = useCallback(() => {
    if (!settings) return
    const updated: Settings = {
      ...settings,
      config: {
        ...settings.config,
        ui: {
          show_llm_call_events: store.showLlmEvents,
          expanded_messages_by_default: store.expandMessages,
          show_agent_flow_by_default: store.showAgentFlow,
          human_input_timeout_minutes: store.humanInputTimeout,
        },
      },
    }
    updateSettings.mutate(updated)
  }, [
    settings,
    store.showLlmEvents,
    store.expandMessages,
    store.showAgentFlow,
    store.humanInputTimeout,
    updateSettings,
  ])

  const handleReset = useCallback(() => {
    if (settings?.config?.ui) {
      hydrate(settings.config.ui)
    }
  }, [settings, hydrate])

  const handleTimeoutChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = parseInt(e.target.value, 10)
      if (!isNaN(val)) {
        store.setHumanInputTimeout(val)
      }
    },
    [store],
  )

  if (isLoading) {
    return (
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Monitor className="w-5 h-5 text-(--color-text-secondary)" />
          <h2 className="text-heading-small">UI Settings</h2>
        </div>
        <p className="text-body-medium text-(--color-text-tertiary)">Loading settings...</p>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Monitor className="w-5 h-5 text-(--color-text-secondary)" />
          <h2 className="text-heading-small">UI Settings</h2>
        </div>
        <p className="text-body-medium text-(--color-semantic-error)">
          Failed to load settings:{' '}
          {truncateError(error instanceof Error ? error.message : String(error))}
        </p>
      </Card>
    )
  }

  return (
    <Card>
      <div className="flex items-center gap-3 mb-4">
        <Monitor className="w-5 h-5 text-(--color-text-secondary)" />
        <h2 className="text-heading-small">UI Settings</h2>
      </div>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-label block">Show LLM Events</span>
            <span className="text-body-small text-(--color-text-tertiary)">
              Display detailed LLM call logs in message threads
            </span>
          </div>
          <Toggle
            checked={store.showLlmEvents}
            onChange={store.setShowLlmEvents}
            aria-label="Toggle show LLM events"
          />
        </div>
        <div className="flex items-center justify-between">
          <div>
            <span className="text-label block">Expand Messages by Default</span>
            <span className="text-body-small text-(--color-text-tertiary)">
              Auto-expand message threads when viewing runs
            </span>
          </div>
          <Toggle
            checked={store.expandMessages}
            onChange={store.setExpandMessages}
            aria-label="Toggle expand messages by default"
          />
        </div>
        <div className="flex items-center justify-between">
          <div>
            <span className="text-label block">Show Agent Flow by Default</span>
            <span className="text-body-small text-(--color-text-tertiary)">
              Auto-display the agent flow diagram when opening teams
            </span>
          </div>
          <Toggle
            checked={store.showAgentFlow}
            onChange={store.setShowAgentFlow}
            aria-label="Toggle show agent flow by default"
          />
        </div>
        <div className="flex items-center justify-between">
          <div>
            <label htmlFor="human-input-timeout" className="text-label block">
              Human Input Timeout
            </label>
            <span className="text-body-small text-(--color-text-tertiary)">
              Minutes to wait for human input (1-30)
            </span>
          </div>
          <Input
            id="human-input-timeout"
            type="number"
            min={1}
            max={30}
            value={store.humanInputTimeout}
            onChange={handleTimeoutChange}
            aria-label="Human input timeout in minutes"
            className="w-20 text-center"
          />
        </div>
        {updateSettings.isError && (
          <p className="text-body-small text-(--color-semantic-error)">
            Save failed:{' '}
            {truncateError(
              updateSettings.error instanceof Error
                ? updateSettings.error.message
                : 'Unknown error',
            )}
          </p>
        )}
        <div className="flex gap-2 pt-2">
          <Button
            onClick={handleSave}
            disabled={!isDirty || updateSettings.isPending}
            aria-label="Save UI settings"
          >
            {updateSettings.isPending ? 'Saving...' : 'Save'}
          </Button>
          <Button
            variant="secondary"
            onClick={handleReset}
            disabled={!isDirty}
            aria-label="Reset UI settings"
          >
            Reset
          </Button>
        </div>
      </div>
    </Card>
  )
}
