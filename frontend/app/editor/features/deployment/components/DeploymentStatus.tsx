import { useQuery } from '@tanstack/react-query'
import { Button, Card, Badge } from '@/elements/workspace'
import { workspaceRequest } from '@/lib/workspace-request'

export function DeploymentStatus() {
  const health = useQuery({
    queryKey: ['deployment-health'],
    queryFn: () => workspaceRequest<{ status: boolean; service: string }>('health'),
    retry: false,
    refetchInterval: 30000,
  })
  const version = useQuery({
    queryKey: ['deployment-version'],
    queryFn: () => workspaceRequest<{ version: string }>('version'),
    retry: false,
  })
  const connected = health.isSuccess && health.data.status === true
  return (
    <Card>
      <div data-testid="deployment-status">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-heading-small">Deployment Status</h2>
          <Button
            size="sm"
            variant="ghost"
            disabled={health.isFetching}
            onClick={() => {
              void health.refetch()
              void version.refetch()
            }}
          >
            Refresh deployment status
          </Button>
        </div>
        <div className="grid md:grid-cols-3 gap-4">
          {[
            [
              'Connection',
              health.isPending ? 'Checking...' : connected ? 'Connected' : 'Disconnected',
            ],
            [
              'Version',
              version.isSuccess
                ? version.data.version
                : version.isPending
                  ? 'Loading...'
                  : 'Unavailable',
            ],
            ['Auto-Refresh', 'Every 30s'],
          ].map(([label, text]) => (
            <div key={label} className="p-4 bg-(--color-background-secondary) rounded-lg">
              <p className="text-label-small mb-2">{label}</p>
              <p>{text}</p>
            </div>
          ))}
        </div>
        <p className="text-body-small mt-4">
          Current Instance: this Editor frontend → /api/v1/workspace → its configured Editor
          backend. Changing the command preview does not change this connection.
        </p>
        <p className="text-body-small mt-2">
          Last checked:{' '}
          {health.dataUpdatedAt
            ? new Date(health.dataUpdatedAt).toLocaleTimeString()
            : 'No successful response yet'}
        </p>
        <div className="mt-4">
          <Badge variant="outline">Not deployed</Badge>
          <span className="text-body-small ml-2">
            Container / cloud — no deployment is initiated by this page.
          </span>
        </div>
      </div>
    </Card>
  )
}
