import { useState } from 'react'
import { Card, Button, Input } from '@/elements/workspace'
import { CopyCommand } from './CopyCommand'

type Variable = { key: string; value: string; secret: boolean; revealed: boolean }
const presets = ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'VWORLD_API_KEY']

export function EnvironmentDraft() {
  const [variables, setVariables] = useState<Variable[]>([])
  const [key, setKey] = useState('')
  const [value, setValue] = useState('')
  const [secret, setSecret] = useState(true)
  const add = (name: string, content = '', hidden = true) => {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name) || variables.some((v) => v.key === name)) return
    setVariables((previous) => [
      ...previous,
      { key: name, value: content, secret: hidden, revealed: false },
    ])
  }
  const update = (name: string, patch: Partial<Variable>) =>
    setVariables((previous) => previous.map((v) => (v.key === name ? { ...v, ...patch } : v)))
  const template = variables.map((v) => `${v.key}=<set-on-server>`).join('\n')
  return (
    <Card>
      <h2 className="text-heading-small mb-3">Environment Variables</h2>
      <p className="text-body-small text-(--color-text-secondary) mb-4">
        Temporary planning draft only. Values are not sent, saved, or included in copied templates.
        Reloading clears this draft. Configure actual values through the server environment.
      </p>
      <div className="flex flex-wrap gap-2 mb-4">
        {presets.map((name) => (
          <Button
            key={name}
            variant="ghost"
            size="sm"
            disabled={variables.some((v) => v.key === name)}
            onClick={() => add(name)}
          >
            {name}
          </Button>
        ))}
      </div>
      <div className="space-y-3">
        {variables.map((v) => (
          <div key={v.key} className="flex flex-wrap items-center gap-2">
            <code className="min-w-44">{v.key}</code>
            <Input
              className="flex-1"
              aria-label={`Value for ${v.key}`}
              value={v.value}
              type={v.secret && !v.revealed ? 'password' : 'text'}
              autoComplete="off"
              onChange={(e) => update(v.key, { value: e.target.value })}
            />
            <label className="text-body-small">
              <input
                type="checkbox"
                aria-label={`Secret ${v.key}`}
                checked={v.secret}
                onChange={(e) => update(v.key, { secret: e.target.checked, revealed: false })}
              />{' '}
              Secret
            </label>
            {v.secret && (
              <Button
                size="sm"
                variant="ghost"
                aria-label={`${v.revealed ? 'Hide' : 'Show'} value for ${v.key}`}
                onClick={() => update(v.key, { revealed: !v.revealed })}
              >
                {v.revealed ? 'Hide' : 'Show'}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Remove ${v.key}`}
              onClick={() =>
                setVariables((previous) => previous.filter((entry) => entry.key !== v.key))
              }
            >
              Remove
            </Button>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3 items-end mt-4">
        <label className="flex-1">
          Key
          <Input
            aria-label="New environment key"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="MY_VARIABLE"
          />
        </label>
        <label className="flex-1">
          Value
          <Input
            aria-label="New environment value"
            type={secret ? 'password' : 'text'}
            autoComplete="off"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <label>
          <input type="checkbox" checked={secret} onChange={(e) => setSecret(e.target.checked)} />{' '}
          Secret
        </label>
        <Button
          variant="secondary"
          disabled={
            !/^[A-Za-z_][A-Za-z0-9_]*$/.test(key.trim()) ||
            variables.some((v) => v.key === key.trim())
          }
          onClick={() => {
            add(key.trim(), value, secret)
            setKey('')
            setValue('')
          }}
        >
          Add environment variable
        </Button>
      </div>
      <div className="mt-4">
        <CopyCommand
          label="Copy environment template"
          text={template}
          disabled={!variables.length}
        />
        <pre data-testid="environment-preview" className="mt-2 whitespace-pre-wrap text-body-small">
          {template || 'Add variables to prepare a server-side template.'}
        </pre>
      </div>
    </Card>
  )
}
