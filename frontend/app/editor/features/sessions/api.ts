import { workspaceRequest } from '@/lib/workspace-request'
import type { Session, SessionRuns } from '@/lib/contracts/workspace'

export const sessionsApi = {
  list: () => workspaceRequest<Session[]>('sessions'),
  runs: (id: number) => workspaceRequest<SessionRuns>(`sessions/${id}/runs`),
  create: (name: string, teamId: number) =>
    workspaceRequest<Session>('sessions', {
      method: 'POST',
      body: JSON.stringify({ name, team_id: teamId }),
    }),
  archive: (id: number) =>
    workspaceRequest<{ archived: boolean }>(`sessions/${id}`, { method: 'DELETE' }),
}
