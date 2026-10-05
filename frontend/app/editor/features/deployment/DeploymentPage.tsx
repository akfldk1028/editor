'use client'
import { Cloud, Container, Terminal } from 'lucide-react'
import { Card, Badge } from '@/elements/workspace'
import { LaunchConfiguration } from './components/LaunchConfiguration'
import { EnvironmentDraft } from './components/EnvironmentDraft'
import { DeploymentStatus } from './components/DeploymentStatus'

const guides = [
  {
    title: 'Local Development',
    Icon: Terminal,
    badge: 'Available',
    description: 'Run the native Editor frontend and Python API from this checkout.',
    steps: [
      'Install workspace and backend dependencies.',
      'Configure server environment values.',
      'Use the separate backend and frontend commands below.',
    ],
  },
  {
    title: 'Docker Deployment',
    Icon: Container,
    badge: 'Not deployed',
    description:
      'Existing infra/docker/compose.yml supports the PLANM subset. A full native Editor container is not yet configured.',
    steps: [
      'Review the existing subset deployment scope.',
      'Define native frontend build and backend services.',
      'Validate storage, secrets and health before deployment.',
    ],
  },
  {
    title: 'Cloud Deployment',
    Icon: Cloud,
    badge: 'Not deployed',
    description: 'Cloud provisioning for the unified Editor is not implemented.',
    steps: [
      'Choose a hosting target.',
      'Configure storage and server-side secrets.',
      'Verify native routes, streaming and agent connectivity.',
    ],
  },
]
const endpoints = [
  ['GET', '/api/v1/workspace/health', 'Editor workspace health'],
  ['GET', '/api/v1/workspace/version', 'Workspace API version'],
  ['GET', '/api/v1/workspace/settings', 'Workspace preferences'],
  ['GET', '/api/v1/workspace/teams', 'Team catalog'],
  ['GET', '/api/v1/workspace/sessions', 'Session history'],
  ['POST', '/api/v1/design/jobs/', 'Create a design job'],
  ['GET', '/api/v1/design/jobs/{job_id}/', 'Design job status'],
]
export function DeploymentPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-display-medium">Deploy</h1>
        <p className="text-body-medium text-(--color-text-secondary) mt-1">
          Editor launch configuration, environment draft, API reference and live connection status
        </p>
      </div>
      <div className="grid lg:grid-cols-3 gap-6">
        {guides.map(({ title, Icon, badge, description, steps }) => (
          <Card key={title}>
            <div className="flex items-center gap-3 mb-4">
              <Icon className="w-5 h-5" />
              <div>
                <h2 className="text-heading-small">{title}</h2>
                <Badge variant="outline">{badge}</Badge>
              </div>
            </div>
            <p className="text-body-small mb-4">{description}</p>
            <ol className="list-decimal ml-5 space-y-2 text-body-small">
              {steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </Card>
        ))}
      </div>
      <LaunchConfiguration />
      <EnvironmentDraft />
      <Card>
        <h2 className="text-heading-small mb-4">API Endpoints Reference</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-body-small">
            <thead>
              <tr className="text-left">
                <th className="p-3">Method</th>
                <th>Endpoint</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {endpoints.map(([method, path, description]) => (
                <tr key={path} className="border-t border-(--color-border-default)">
                  <td className="p-3">
                    <Badge variant={method === 'GET' ? 'success' : 'primary'}>{method}</Badge>
                  </td>
                  <td className="font-mono">{path}</td>
                  <td>{description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <DeploymentStatus />
    </div>
  )
}
