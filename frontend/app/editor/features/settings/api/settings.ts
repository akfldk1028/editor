import type { Settings } from '../model/types'
import { workspaceRequest } from '@/lib/workspace-request'
export const settingsAPI = {
  get: () => workspaceRequest<Settings>('settings'),
  update: (settings: Settings) =>
    workspaceRequest<Settings>('settings', { method: 'PUT', body: JSON.stringify(settings) }),
}
