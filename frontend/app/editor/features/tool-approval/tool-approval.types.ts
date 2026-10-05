export type ToolIcon = 'edit' | 'read' | 'execute' | 'fetch' | 'generic'

export interface ToolApproval {
  id: string
  toolName: string
  args: string
  icon: ToolIcon
  source: string
  timestamp: string
  status: 'pending' | 'approved' | 'rejected'
}

export interface ToolCallInfo {
  name: string
  args: string
  result?: string
  status: 'pending' | 'success' | 'error'
  duration?: number
}
