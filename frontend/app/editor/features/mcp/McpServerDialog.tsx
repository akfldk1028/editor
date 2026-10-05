/**
 * McpServerDialog - Dialog for adding a new MCP server
 * Supports Stdio, SSE, and StreamableHTTP server types with
 * conditional fields based on the selected type.
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Button, Input, Card, Toggle } from '@/elements/workspace'
import { X, Plus } from 'lucide-react'
import { useMcpStore } from './mcpStore'
import type { McpServerType } from './mcpStore'

interface McpServerDialogProps {
  open: boolean
  onClose: () => void
}

interface ServerTypeOption {
  type: McpServerType
  label: string
  description: string
}

const SERVER_TYPES: ServerTypeOption[] = [
  { type: 'stdio', label: 'Stdio', description: 'Local process via stdin/stdout' },
  { type: 'sse', label: 'SSE', description: 'Server-Sent Events over HTTP' },
  { type: 'streamable_http', label: 'Streamable HTTP', description: 'HTTP streaming with optional SSE' },
]

function buildParams(type: McpServerType, fields: Record<string, string>, terminateOnClose: boolean): Record<string, unknown> {
  switch (type) {
    case 'stdio': {
      const params: Record<string, unknown> = {
        type: 'StdioServerParams',
        command: fields.command || '',
      }
      if (fields.args?.trim()) {
        params.args = fields.args.split(',').map((a) => a.trim()).filter(Boolean)
      }
      if (fields.env?.trim()) {
        const env: Record<string, string> = {}
        for (const line of fields.env.split('\n')) {
          const eqIdx = line.indexOf('=')
          if (eqIdx > 0) {
            env[line.slice(0, eqIdx).trim()] = line.slice(eqIdx + 1).trim()
          }
        }
        if (Object.keys(env).length > 0) params.env = env
      }
      if (fields.readTimeout?.trim()) {
        const num = Number(fields.readTimeout)
        if (!Number.isNaN(num) && num > 0) params.read_timeout_seconds = num
      }
      return params
    }
    case 'sse': {
      const params: Record<string, unknown> = {
        type: 'SseServerParams',
        url: fields.url || '',
      }
      if (fields.timeout?.trim()) {
        const num = Number(fields.timeout)
        if (!Number.isNaN(num) && num > 0) params.timeout = num
      }
      return params
    }
    case 'streamable_http': {
      const params: Record<string, unknown> = {
        type: 'StreamableHttpServerParams',
        url: fields.url || '',
        terminate_on_close: terminateOnClose,
      }
      if (fields.timeout?.trim()) {
        const num = Number(fields.timeout)
        if (!Number.isNaN(num) && num > 0) params.timeout = num
      }
      return params
    }
  }
}

export function McpServerDialog({ open, onClose }: McpServerDialogProps) {
  const addServer = useMcpStore((s) => s.addServer)

  const [name, setName] = useState('')
  const [serverType, setServerType] = useState<McpServerType>('stdio')
  const [fields, setFields] = useState<Record<string, string>>({})
  const [terminateOnClose, setTerminateOnClose] = useState(true)

  useEffect(() => {
    if (open) {
      setName('')
      setServerType('stdio')
      setFields({})
      setTerminateOnClose(true)
    }
  }, [open])

  const updateField = useCallback((key: string, value: string) => {
    setFields((prev) => ({ ...prev, [key]: value }))
  }, [])

  const isValid = useMemo(() => {
    if (!name.trim()) return false
    if (serverType === 'stdio' && !fields.command?.trim()) return false
    if ((serverType === 'sse' || serverType === 'streamable_http') && !fields.url?.trim()) return false
    return true
  }, [name, serverType, fields])

  const handleAdd = useCallback(() => {
    if (!isValid) return
    const params = buildParams(serverType, fields, terminateOnClose)
    addServer({ name: name.trim(), type: serverType, params })
    onClose()
  }, [name, serverType, fields, terminateOnClose, addServer, onClose, isValid])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label="Add MCP server"
      onClick={onClose}
      onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}
    >
      <Card className="w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-heading-small">Add MCP Server</h2>
          <button
            onClick={onClose}
            aria-label="Close add server dialog"
            className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-4">
          {/* Server Name */}
          <div>
            <label htmlFor="mcp-server-name" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
              Server Name <span className="text-(--color-semantic-error)">*</span>
            </label>
            <Input
              id="mcp-server-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My MCP Server"
            />
          </div>

          {/* Server Type */}
          <div>
            <label className="text-sm font-medium text-(--color-text-secondary) mb-2 block">
              Server Type
            </label>
            <div className="space-y-2" role="radiogroup" aria-label="Server type selector">
              {SERVER_TYPES.map((opt) => {
                const isSelected = serverType === opt.type
                return (
                  <div
                    key={opt.type}
                    role="radio"
                    aria-checked={isSelected}
                    tabIndex={isSelected ? 0 : -1}
                    onClick={() => { setServerType(opt.type); setFields({}) }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setServerType(opt.type)
                        setFields({})
                      }
                    }}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                      isSelected
                        ? 'ring-2 ring-(--color-accent-primary) border-(--color-accent-primary) bg-(--color-background-secondary)'
                        : 'border-(--color-border-default) hover:border-(--color-accent-primary)'
                    }`}
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{opt.label}</p>
                      <p className="text-xs text-(--color-text-tertiary)">{opt.description}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Conditional Fields: Stdio */}
          {serverType === 'stdio' && (
            <>
              <div>
                <label htmlFor="mcp-stdio-command" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
                  Command <span className="text-(--color-semantic-error)">*</span>
                </label>
                <Input
                  id="mcp-stdio-command"
                  value={fields.command ?? ''}
                  onChange={(e) => updateField('command', e.target.value)}
                  placeholder="python"
                />
              </div>
              <div>
                <label htmlFor="mcp-stdio-args" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
                  Arguments (comma-separated)
                </label>
                <Input
                  id="mcp-stdio-args"
                  value={fields.args ?? ''}
                  onChange={(e) => updateField('args', e.target.value)}
                  placeholder="--host, localhost, --port, 8080"
                />
              </div>
              <div>
                <label htmlFor="mcp-stdio-env" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
                  Environment Variables (KEY=VALUE per line)
                </label>
                <textarea
                  id="mcp-stdio-env"
                  value={fields.env ?? ''}
                  onChange={(e) => updateField('env', e.target.value)}
                  placeholder={"API_KEY=sk-...\nDEBUG=true"}
                  rows={3}
                  className="w-full px-4 py-2 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-(--color-text-primary) text-sm focus:outline-none focus:border-(--color-accent-primary) focus:ring-2 focus:ring-(--color-accent-primary)/20 placeholder:text-(--color-text-tertiary) resize-none"
                />
                <p className="text-xs text-(--color-text-tertiary) mt-1">Environment values are kept only for this page session. Prefer server environment configuration for credentials.</p>
              </div>
              <div>
                <label htmlFor="mcp-stdio-timeout" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
                  Read Timeout (seconds)
                </label>
                <Input
                  id="mcp-stdio-timeout"
                  type="number"
                  min={1}
                  value={fields.readTimeout ?? ''}
                  onChange={(e) => updateField('readTimeout', e.target.value)}
                  placeholder="30"
                />
              </div>
            </>
          )}

          {/* Conditional Fields: SSE */}
          {serverType === 'sse' && (
            <>
              <div>
                <label htmlFor="mcp-sse-url" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
                  Server URL <span className="text-(--color-semantic-error)">*</span>
                </label>
                <Input
                  id="mcp-sse-url"
                  value={fields.url ?? ''}
                  onChange={(e) => updateField('url', e.target.value)}
                  placeholder="http://localhost:3001/sse"
                />
              </div>
              <div>
                <label htmlFor="mcp-sse-timeout" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
                  Timeout (seconds)
                </label>
                <Input
                  id="mcp-sse-timeout"
                  type="number"
                  min={1}
                  value={fields.timeout ?? ''}
                  onChange={(e) => updateField('timeout', e.target.value)}
                  placeholder="30"
                />
              </div>
            </>
          )}

          {/* Conditional Fields: Streamable HTTP */}
          {serverType === 'streamable_http' && (
            <>
              <div>
                <label htmlFor="mcp-http-url" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
                  Server URL <span className="text-(--color-semantic-error)">*</span>
                </label>
                <Input
                  id="mcp-http-url"
                  value={fields.url ?? ''}
                  onChange={(e) => updateField('url', e.target.value)}
                  placeholder="http://localhost:3001/mcp"
                />
              </div>
              <div>
                <label htmlFor="mcp-http-timeout" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
                  Timeout (seconds)
                </label>
                <Input
                  id="mcp-http-timeout"
                  type="number"
                  min={1}
                  value={fields.timeout ?? ''}
                  onChange={(e) => updateField('timeout', e.target.value)}
                  placeholder="30"
                />
              </div>
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-(--color-text-secondary)">
                  Terminate on Close
                </label>
                <Toggle checked={terminateOnClose} onChange={setTerminateOnClose} />
              </div>
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            onClick={handleAdd}
            disabled={!isValid}
          >
            <Plus className="w-4 h-4 mr-1.5" />
            Add Server
          </Button>
        </div>
      </Card>
    </div>
  )
}
