import { Button, Card, Input } from '@/elements/workspace'
import { Plus, Variable } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSettings, useUpdateSettings } from '../hooks/useSettings'
import { truncateError } from '@/lib/display-error'
import type { EnvironmentVariable, EnvironmentVariableType, Settings } from '../model/types'
import { EnvVarRow } from './EnvironmentVariableRow'
const ENV_PRESETS: { name: string; type: EnvironmentVariableType; description: string }[] = [
  { name: 'OPENAI_API_KEY', type: 'secret', description: 'OpenAI API key for GPT models' },
  { name: 'ANTHROPIC_API_KEY', type: 'secret', description: 'Anthropic API key for Claude models' },
]

const ENV_TYPE_OPTIONS: EnvironmentVariableType[] = ['string', 'number', 'boolean', 'secret']

export function EnvironmentVariablesCard() {
  const { data: settings } = useSettings()
  const updateSettings = useUpdateSettings()

  const [envVars, setEnvVars] = useState<EnvironmentVariable[]>([])
  const [newName, setNewName] = useState('')
  const [newValue, setNewValue] = useState('')
  const [newType, setNewType] = useState<EnvironmentVariableType>('string')
  const [nameError, setNameError] = useState<string | null>(null)

  const initializedRef = useRef(false)

  // Hydrate from API
  useEffect(() => {
    if (settings?.config?.environment && !initializedRef.current) {
      setEnvVars(settings.config.environment)
      initializedRef.current = true
    }
  }, [settings])

  const isDirty = useMemo(() => {
    if (!settings?.config?.environment) return envVars.length > 0
    return JSON.stringify(envVars) !== JSON.stringify(settings.config.environment)
  }, [envVars, settings])

  const existingNames = useMemo(() => new Set(envVars.map((v) => v.name)), [envVars])

  const handleAdd = useCallback(() => {
    const trimmedName = newName.trim()
    if (!trimmedName) {
      setNameError('Name is required')
      return
    }
    if (existingNames.has(trimmedName)) {
      setNameError('Variable name already exists')
      return
    }
    setNameError(null)
    setEnvVars((prev) => [
      ...prev,
      { name: trimmedName, value: newValue, type: newType, required: false },
    ])
    setNewName('')
    setNewValue('')
    setNewType('string')
  }, [newName, newValue, newType, existingNames])

  const handleAddPreset = useCallback(
    (preset: (typeof ENV_PRESETS)[0]) => {
      if (existingNames.has(preset.name)) return
      setEnvVars((prev) => [
        ...prev,
        {
          name: preset.name,
          value: '',
          type: preset.type,
          description: preset.description,
          required: false,
        },
      ])
    },
    [existingNames],
  )

  const handleDelete = useCallback((name: string) => {
    setEnvVars((prev) => prev.filter((v) => v.name !== name))
  }, [])

  const handleValueChange = useCallback((name: string, value: string) => {
    setEnvVars((prev) => prev.map((v) => (v.name === name ? { ...v, value } : v)))
  }, [])

  const handleSave = useCallback(() => {
    if (!settings) return
    const updated: Settings = {
      ...settings,
      config: {
        ...settings.config,
        environment: envVars,
      },
    }
    updateSettings.mutate(updated)
  }, [settings, envVars, updateSettings])

  const handleNewNameChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setNewName(e.target.value)
    setNameError(null)
  }, [])

  const handleNewValueChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setNewValue(e.target.value)
  }, [])

  const handleNewTypeChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setNewType(e.target.value as EnvironmentVariableType)
  }, [])

  return (
    <Card>
      <div className="flex items-center gap-3 mb-4">
        <Variable className="w-5 h-5 text-(--color-text-secondary)" />
        <h2 className="text-heading-small">Environment Variables</h2>
      </div>

      {/* Preset buttons */}
      <div className="flex gap-2 mb-4">
        {ENV_PRESETS.map((preset) => (
          <Button
            key={preset.name}
            variant="secondary"
            size="sm"
            disabled={existingNames.has(preset.name)}
            onClick={() => handleAddPreset(preset)}
            aria-label={`Add preset ${preset.name}`}
          >
            <Plus className="w-3 h-3 mr-1" />
            {preset.name}
          </Button>
        ))}
      </div>

      {/* Env vars table */}
      {envVars.length > 0 && (
        <div className="overflow-x-auto mb-4">
          <table className="w-full text-sm" aria-label="Environment variables">
            <thead>
              <tr className="border-b border-(--color-border-default) text-(--color-text-tertiary)">
                <th className="py-2 pr-3 text-left text-label-small font-medium">Name</th>
                <th className="py-2 pr-3 text-left text-label-small font-medium">Value</th>
                <th className="py-2 pr-3 text-left text-label-small font-medium">Type</th>
                <th className="py-2 pr-3 text-left text-label-small font-medium">Description</th>
                <th className="py-2 text-left text-label-small font-medium w-10" />
              </tr>
            </thead>
            <tbody>
              {envVars.map((envVar) => (
                <EnvVarRow
                  key={envVar.name}
                  envVar={envVar}
                  onDelete={handleDelete}
                  onValueChange={handleValueChange}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {envVars.length === 0 && (
        <p className="text-body-medium text-(--color-text-tertiary) mb-4">
          No environment variables configured. Add presets above or create a custom variable below.
        </p>
      )}

      {/* Add new variable */}
      <div className="flex items-end gap-2 flex-wrap">
        <div className="flex-1 min-w-[140px]">
          <label htmlFor="env-new-name" className="text-label-small block mb-1">
            Name
          </label>
          <Input
            id="env-new-name"
            value={newName}
            onChange={handleNewNameChange}
            placeholder="VARIABLE_NAME"
            aria-label="New variable name"
            className={nameError ? 'border-(--color-semantic-error)' : ''}
          />
          {nameError && (
            <p className="text-body-small text-(--color-semantic-error) mt-1">{nameError}</p>
          )}
        </div>
        <div className="flex-1 min-w-[140px]">
          <label htmlFor="env-new-value" className="text-label-small block mb-1">
            Value
          </label>
          <Input
            id="env-new-value"
            value={newValue}
            onChange={handleNewValueChange}
            placeholder="value"
            type={newType === 'secret' ? 'password' : 'text'}
            aria-label="New variable value"
          />
        </div>
        <div className="min-w-[100px]">
          <label htmlFor="env-new-type" className="text-label-small block mb-1">
            Type
          </label>
          <select
            id="env-new-type"
            value={newType}
            onChange={handleNewTypeChange}
            aria-label="New variable type"
            className="h-10 w-full px-3 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-(--color-text-primary) text-sm focus:outline-none focus:border-(--color-accent-primary) focus:ring-2 focus:ring-(--color-accent-primary)/20"
          >
            {ENV_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <Button onClick={handleAdd} size="md" aria-label="Add environment variable">
          <Plus className="w-4 h-4 mr-1" />
          Add
        </Button>
      </div>

      {/* Save */}
      {updateSettings.isError && (
        <p className="text-body-small text-(--color-semantic-error) mt-3">
          Save failed:{' '}
          {truncateError(
            updateSettings.error instanceof Error ? updateSettings.error.message : 'Unknown error',
          )}
        </p>
      )}
      <div className="flex gap-2 pt-4">
        <Button
          onClick={handleSave}
          disabled={!isDirty || updateSettings.isPending}
          aria-label="Save environment variables"
        >
          {updateSettings.isPending ? 'Saving...' : 'Save'}
        </Button>
      </div>
    </Card>
  )
}
