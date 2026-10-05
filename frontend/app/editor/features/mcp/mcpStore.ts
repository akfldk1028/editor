/**
 * mcpStore - Zustand store for MCP server management
 * Persists servers to localStorage across sessions.
 * Tracks live MCP sessions.
 */

import { create } from 'zustand'
import type { McpClient } from '@/features/mcp/api/mcp-client'

// --------------- Types ---------------

export interface McpTool {
  name: string
  description: string
  inputSchema: Record<string, unknown>
}

export type McpServerType = 'stdio' | 'sse' | 'streamable_http'
export type McpServerStatus = 'connected' | 'disconnected' | 'error' | 'connecting'

export interface McpServer {
  id: string
  name: string
  type: McpServerType
  params: Record<string, unknown>
  status: McpServerStatus
  tools: McpTool[]
  lastChecked: string | null
}

// --------------- Store ---------------

const STORAGE_KEY = 'editor:mcp-servers:v1'

export function persistentParams(params: Record<string, unknown>) {
  const allowed = ['type', 'command', 'args', 'url', 'timeout', 'read_timeout_seconds', 'terminate_on_close']
  const result = Object.fromEntries(Object.entries(params).filter(([key]) => allowed.includes(key)))
  if (typeof result.url === 'string') {
    try {
      const url = new URL(result.url)
      if (url.username || url.password || url.search || url.hash) delete result.url
    } catch { delete result.url }
  }
  return result
}

function loadServers(): McpServer[] {
  if (typeof window === 'undefined') return []
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored) as McpServer[]
      // Reset status on reload (no live connection)
      return parsed.map((s) => ({ ...s, params: persistentParams(s.params), status: 'disconnected' as const, tools: [] }))
    }
  } catch { /* use empty */ }
  return []
}

function persistServers(servers: McpServer[]) {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(servers.map((server) => ({
      ...server, params: persistentParams(server.params), tools: [], status: 'disconnected',
    }))))
  } catch { /* Browser storage is optional; session configuration remains usable. */ }
}

interface McpState {
  servers: McpServer[]
  selectedServerId: string | null
  selectedToolName: string | null
  connections: Record<string, McpClient>
  connectingId: string | null
  addServer: (server: Omit<McpServer, 'id' | 'status' | 'tools' | 'lastChecked'>) => void
  removeServer: (id: string) => void
  updateServerStatus: (id: string, status: McpServerStatus, tools?: McpTool[]) => void
  selectServer: (id: string | null) => void
  selectTool: (name: string | null) => void
  setConnection: (serverId: string, ws: McpClient) => void
  removeConnection: (serverId: string) => void
  setConnecting: (serverId: string | null) => void
}

export const useMcpStore = create<McpState>((set, get) => ({
  servers: [],
  selectedServerId: null,
  selectedToolName: null,
  connections: {},
  connectingId: null,

  addServer: (server) => {
    const newServer: McpServer = {
      ...server,
      id: crypto.randomUUID(),
      status: 'disconnected',
      tools: [],
      lastChecked: null,
    }
    const updated = [...get().servers, newServer]
    persistServers(updated)
    set({ servers: updated })
  },

  removeServer: (id) => {
    // Disconnect if connected
    const conn = get().connections[id]
    if (conn) {
      conn.disconnect()
    }
    const { [id]: _removed, ...remainingConns } = get().connections

    const updated = get().servers.filter((s) => s.id !== id)
    persistServers(updated)
    if (get().selectedServerId === id) {
      set({ servers: updated, selectedServerId: null, selectedToolName: null, connections: remainingConns })
    } else {
      set({ servers: updated, connections: remainingConns })
    }
  },

  updateServerStatus: (id, status, tools) => {
    const updated = get().servers.map((s) =>
      s.id === id
        ? { ...s, status, tools: tools ?? s.tools, lastChecked: new Date().toISOString() }
        : s,
    )
    persistServers(updated)
    set({ servers: updated })
  },

  selectServer: (id) => set({ selectedServerId: id, selectedToolName: null }),

  selectTool: (name) => set({ selectedToolName: name }),

  setConnection: (serverId, ws) => {
    set((prev) => ({
      connections: { ...prev.connections, [serverId]: ws },
    }))
  },

  removeConnection: (serverId) => {
    const conn = get().connections[serverId]
    if (conn) {
      conn.disconnect()
    }
    set((prev) => {
      const { [serverId]: _removed, ...rest } = prev.connections
      return { connections: rest,
        servers: prev.servers.map(server => server.id === serverId
          ? { ...server, status: 'disconnected' as const, tools: [] } : server),
        connectingId: prev.connectingId === serverId ? null : prev.connectingId,
        selectedToolName: prev.selectedServerId === serverId ? null : prev.selectedToolName,
      }
    })
  },

  setConnecting: (serverId) => set({ connectingId: serverId }),
}))

export function hydrateMcpServers() {
  if (!useMcpStore.getState().servers.length) useMcpStore.setState({ servers: loadServers() })
}
