/**
 * McpPage - MCP server management, tool browser, and test workbench
 * Three sections: Server list (left), Tool browser (right), Test workbench (bottom full-width)
 * Uses the native Editor MCP session API.
 */

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { Card, Badge, Button } from '@/elements/workspace'
import {
  Wrench,
  Plus,
  Play,
  Server,
  RefreshCw,
  Loader2,
} from 'lucide-react'
import { useMcpStore, hydrateMcpServers } from './mcpStore'
import type { McpServer, McpTool } from './mcpStore'
import { McpServerDialog } from './McpServerDialog'
import { McpClient } from '@/features/mcp/api/mcp-client'
import { ServerCard, ToolCard, buildSchemaTemplate } from './McpCards'
import { McpResources } from './McpResources'

// --------------- Sub-components ---------------

// --------------- Main Page ---------------

export function McpPage() {
  const servers = useMcpStore((s) => s.servers)
  const selectedServerId = useMcpStore((s) => s.selectedServerId)
  const selectedToolName = useMcpStore((s) => s.selectedToolName)
  const connectingId = useMcpStore((s) => s.connectingId)
  const connections = useMcpStore((s) => s.connections)
  const selectServer = useMcpStore((s) => s.selectServer)
  const selectTool = useMcpStore((s) => s.selectTool)
  const removeServer = useMcpStore((s) => s.removeServer)
  const updateServerStatus = useMcpStore((s) => s.updateServerStatus)
  const setConnection = useMcpStore((s) => s.setConnection)
  const removeConnection = useMcpStore((s) => s.removeConnection)
  const setConnecting = useMcpStore((s) => s.setConnecting)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [toolInput, setToolInput] = useState('')
  const [testOutput, setTestOutput] = useState<string | null>(null)
  const [executing, setExecuting] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const execution = useRef(0)
  useEffect(hydrateMcpServers, [])
  useEffect(() => () => {
    execution.current++
    for (const id of Object.keys(useMcpStore.getState().connections)) {
      useMcpStore.getState().removeConnection(id)
    }
  }, [])

  const selectedServer = useMemo(
    () => servers.find((s) => s.id === selectedServerId) ?? null,
    [servers, selectedServerId],
  )

  const selectedTool = useMemo(
    () => selectedServer?.tools.find((t) => t.name === selectedToolName) ?? null,
    [selectedServer, selectedToolName],
  )

  const isSelectedConnected = selectedServer?.status === 'connected' && selectedServerId != null && connections[selectedServerId] != null

  // When a tool is selected, pre-fill the input with a schema template
  const handleSelectTool = useCallback((name: string) => {
    execution.current++
    setExecuting(false)
    selectTool(name)
    setTestOutput(null)
    const server = useMcpStore.getState().servers.find((s) => s.id === useMcpStore.getState().selectedServerId)
    const tool = server?.tools.find((t) => t.name === name)
    if (tool) {
      setToolInput(buildSchemaTemplate(tool.inputSchema))
    } else {
      setToolInput('{}')
    }
  }, [selectTool])

  const handleSelectServer = useCallback((id: string) => {
    execution.current++
    setExecuting(false)
    selectServer(id)
    setTestOutput(null)
    setToolInput('')
  }, [selectServer])

  const handleRemoveServer = useCallback((id: string) => {
    execution.current++
    setExecuting(false)
    removeServer(id)
    setTestOutput(null)
    setToolInput('')
  }, [removeServer])

  const handleCheckHealth = useCallback(async (server: McpServer) => {
    const existing = useMcpStore.getState().connections[server.id]
    if (existing) {
      removeConnection(server.id)
      updateServerStatus(server.id, 'disconnected', [])
      execution.current++
      setExecuting(false)
      return
    }
    setConnectionError(null)
    setConnecting(server.id)
    updateServerStatus(server.id, 'connecting')
    const client = new McpClient({ serverParams: server.params })
    setConnection(server.id, client)
    const current = () => useMcpStore.getState().connections[server.id] === client
    try {
      await client.connect()
      if (!current() || !client.isConnected) return
      const result = await client.listTools()
      if (!current()) return
      if (result.type === 'operation_error') throw new Error(result.error || 'Tool discovery failed')
      const tools = (result.data as { tools?: McpTool[] })?.tools
      if (!Array.isArray(tools)) throw new Error('Invalid MCP tools response')
      updateServerStatus(server.id, 'connected', tools)
    } catch (error) {
      if (!current()) return
      removeConnection(server.id)
      updateServerStatus(server.id, 'error', [])
      setConnectionError(error instanceof Error ? error.message : 'MCP connection failed')
    } finally {
      if (useMcpStore.getState().connectingId === server.id) setConnecting(null)
    }
  }, [removeConnection, updateServerStatus, setConnecting, setConnection])

  const handleOpenDialog = useCallback(() => setDialogOpen(true), [])
  const handleCloseDialog = useCallback(() => setDialogOpen(false), [])

  const handleExecuteTest = useCallback(async () => {
    if (!selectedTool || !selectedServerId) return
    const conn = connections[selectedServerId]
    if (!conn?.isConnected) return
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(toolInput)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
    } catch {
      setTestOutput(JSON.stringify({ error: 'Input must be a JSON object' }, null, 2))
      return
    }
    const token = ++execution.current
    setExecuting(true)
    setTestOutput(null)
    try {
      const result = await conn.callTool(selectedTool.name, parsed)
      if (token !== execution.current) return
      setTestOutput(JSON.stringify(result.type === 'operation_error'
        ? { status: 'error', tool: selectedTool.name, error: result.error }
        : { status: 'success', tool: selectedTool.name, result: result.data }, null, 2))
    } finally {
      if (token === execution.current) setExecuting(false)
    }
  }, [selectedTool, selectedServerId, connections, toolInput])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-display-medium">MCP</h1>
          <p className="text-body-medium text-(--color-text-secondary) mt-1">
            Model Context Protocol workbench
          </p>
        </div>
        <Button onClick={handleOpenDialog}>
          <Plus className="w-4 h-4 mr-2" />
          Add Server
        </Button>
      </div>

      {connectionError && <p role="alert">{connectionError}</p>}
      {/* Main grid: Servers + Tools */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Section 1: MCP Servers */}
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <Server className="w-5 h-5 text-(--color-text-secondary)" />
            <h2 className="text-heading-small">MCP Servers</h2>
            <span className="text-xs text-(--color-text-tertiary) ml-auto">
              {servers.length} server{servers.length !== 1 ? 's' : ''}
            </span>
          </div>

          {servers.length === 0 ? (
            <div className="text-center py-8">
              <Server className="w-12 h-12 mx-auto text-(--color-text-tertiary) mb-3" />
              <p className="text-body-small text-(--color-text-tertiary)">
                No MCP servers configured
              </p>
              <p className="text-xs text-(--color-text-tertiary) mt-1">
                Add a server to get started
              </p>
              <Button variant="secondary" size="sm" className="mt-3" onClick={handleOpenDialog}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />
                Add Server
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              {servers.map((server) => (
                <ServerCard
                  key={server.id}
                  server={server}
                  isSelected={selectedServerId === server.id}
                  isConnecting={connectingId === server.id}
                  onSelect={() => handleSelectServer(server.id)}
                  onRemove={() => handleRemoveServer(server.id)}
                  onCheckHealth={() => handleCheckHealth(server)}
                />
              ))}
            </div>
          )}
        </Card>

        {/* Section 2: Available Tools */}
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <Wrench className="w-5 h-5 text-(--color-text-secondary)" />
            <h2 className="text-heading-small">Available Tools</h2>
            {selectedServer && selectedServer.tools.length > 0 && (
              <span className="text-xs text-(--color-text-tertiary) ml-auto">
                {selectedServer.tools.length} tool{selectedServer.tools.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>

          {!selectedServer ? (
            <div className="text-center py-8">
              <Wrench className="w-12 h-12 mx-auto text-(--color-text-tertiary) mb-3" />
              <p className="text-body-small text-(--color-text-tertiary)">
                Select a server to browse tools
              </p>
            </div>
          ) : selectedServer.status === 'connecting' ? (
            <div className="text-center py-8">
              <Loader2 className="w-12 h-12 mx-auto text-(--color-text-tertiary) mb-3 animate-spin" />
              <p className="text-body-small text-(--color-text-tertiary)">
                Connecting to server...
              </p>
            </div>
          ) : selectedServer.status !== 'connected' ? (
            <div className="text-center py-8">
              <RefreshCw className="w-12 h-12 mx-auto text-(--color-text-tertiary) mb-3" />
              <p className="text-body-small text-(--color-text-tertiary)">
                Server is not connected
              </p>
              <p className="text-xs text-(--color-text-tertiary) mt-1">
                Click the refresh button to connect and discover tools
              </p>
            </div>
          ) : selectedServer.tools.length === 0 ? (
            <div className="text-center py-8">
              <Wrench className="w-12 h-12 mx-auto text-(--color-text-tertiary) mb-3" />
              <p className="text-body-small text-(--color-text-tertiary)">
                No tools discovered
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {selectedServer.tools.map((tool) => (
                <ToolCard
                  key={tool.name}
                  tool={tool}
                  isSelected={selectedToolName === tool.name}
                  onSelect={() => handleSelectTool(tool.name)}
                />
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Section 3: Test Workbench */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Play className="w-5 h-5 text-(--color-text-secondary)" />
          <h2 className="text-heading-small">Test Workbench</h2>
        </div>

        {!selectedTool ? (
          <p className="text-body-medium text-(--color-text-tertiary)">
            Select a tool above to test it interactively.
          </p>
        ) : (
          <div className="space-y-4">
            {/* Selected tool info */}
            <div className="flex items-center gap-3 p-3 rounded-lg bg-(--color-background-secondary)">
              <Wrench className="w-4 h-4 text-(--color-accent-primary) flex-shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-medium font-mono">{selectedTool.name}</p>
                <p className="text-xs text-(--color-text-tertiary)">{selectedTool.description}</p>
              </div>
            </div>

            {/* Input schema info */}
            {'properties' in selectedTool.inputSchema && selectedTool.inputSchema.properties != null && (
              <div>
                <p className="text-xs font-medium text-(--color-text-secondary) mb-1">Parameters</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(selectedTool.inputSchema.properties as Record<string, Record<string, unknown>>).map(
                    ([paramName, paramDef]) => {
                      const required = Array.isArray(selectedTool.inputSchema.required) &&
                        (selectedTool.inputSchema.required as string[]).includes(paramName)
                      return (
                        <span key={paramName} className="flex items-center gap-1">
                          <Badge variant={required ? 'primary' : 'outline'}>
                            {paramName}: {String(paramDef.type ?? 'any')}
                          </Badge>
                        </span>
                      )
                    },
                  )}
                </div>
              </div>
            )}

            {/* JSON input */}
            <div>
              <label htmlFor="tool-input" className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
                Input (JSON)
              </label>
              <textarea
                id="tool-input"
                value={toolInput}
                onChange={(e) => setToolInput(e.target.value)}
                rows={6}
                spellCheck={false}
                className="w-full px-4 py-3 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-(--color-text-primary) text-sm font-mono focus:outline-none focus:border-(--color-accent-primary) focus:ring-2 focus:ring-(--color-accent-primary)/20 placeholder:text-(--color-text-tertiary) resize-y"
                placeholder='{ "param": "value" }'
              />
            </div>

            {/* Execute */}
            <div className="flex items-center gap-3">
              <Button
                variant="primary"
                onClick={handleExecuteTest}
                disabled={!isSelectedConnected || executing}
              >
                {executing ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                    Executing...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 mr-1.5" />
                    Execute
                  </>
                )}
              </Button>
              {!isSelectedConnected && (
                <span className="text-xs text-(--color-text-tertiary)">
                  Connect to server first to execute tools
                </span>
              )}
            </div>

            {/* Output */}
            {testOutput !== null && (
              <div>
                <p className="text-sm font-medium text-(--color-text-secondary) mb-1">Output</p>
                <pre className="w-full px-4 py-3 rounded-md border border-(--color-border-default) bg-(--color-background-secondary) text-(--color-text-primary) text-sm font-mono overflow-x-auto max-h-64 overflow-y-auto">
                  {testOutput}
                </pre>
              </div>
            )}
          </div>
        )}
      </Card>

      <McpResources key={selectedServerId} connection={selectedServerId ? connections[selectedServerId] : undefined} />

      {/* Add Server Dialog */}
      <McpServerDialog open={dialogOpen} onClose={handleCloseDialog} />
    </div>
  )
}
