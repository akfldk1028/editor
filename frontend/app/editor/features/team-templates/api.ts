import type { Component, ComponentConfig, TeamConfig } from '@/lib/contracts/workspace'
import { workspaceRequest } from '@/lib/workspace-request'
export interface TeamResponse {
  id: number
  version: number
  component: Component<TeamConfig> | null
  created_at: string
  updated_at: string
  execution_status: 'not_executed'
}
export interface ValidationError {
  field: string
  error: string
  suggestion?: string
}
export interface ValidationResponse {
  is_valid: boolean
  errors: ValidationError[]
  warnings: ValidationError[]
  scope: string
}
export interface ComponentTestResult {
  status: boolean
  message: string
  data?: unknown
  logs: string[]
}
export const teamAPI = {
  list: () => workspaceRequest<TeamResponse[]>('teams'),
  get: (id: number) => workspaceRequest<TeamResponse>(`teams/${id}`),
  create: (body: Record<string, unknown>) =>
    workspaceRequest<TeamResponse>('teams', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: number, component: unknown, version: number) =>
    workspaceRequest<TeamResponse>(`teams/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ component, version }),
    }),
  delete: (id: number) =>
    workspaceRequest<{ deleted: boolean }>(`teams/${id}`, { method: 'DELETE' }),
}
export const validationAPI = {
  validate: (component: Component<ComponentConfig>) =>
    workspaceRequest<ValidationResponse>('validate', {
      method: 'POST',
      body: JSON.stringify({ component }),
    }),
  test: (component: Component<ComponentConfig>, timeout = 60) =>
    workspaceRequest<ComponentTestResult>('validate/test', {
      method: 'POST',
      body: JSON.stringify({ component, timeout }),
    }),
}
