import { workspaceRequest } from '@/lib/workspace-request'
import { sessionsApi } from '@/features/sessions/api'

export const api = {
  getSessions: sessionsApi.list,
  getSessionRuns: sessionsApi.runs,
  createSession: (teamId: number) => sessionsApi.create('Playground session', teamId),
  createRun: (sessionId: number) => workspaceRequest<{run_id: string; session_id: number}>('runs', {
    method: 'POST', body: JSON.stringify({session_id: sessionId}),
  }),
}
