import { useState } from 'react'
import { Card, Button, Input } from '@/elements/workspace'
import { CopyCommand } from './CopyCommand'

export function LaunchConfiguration() {
  const [backendPort, setBackendPort] = useState('18449')
  const [frontendPort, setFrontendPort] = useState('3003')
  const validPort = (value: string) =>
    /^\d+$/.test(value) && Number(value) > 0 && Number(value) <= 65535
  const valid =
    validPort(backendPort) &&
    validPort(frontendPort) &&
    Number(backendPort) !== Number(frontendPort)
  const backend = valid
    ? `Set-Location -LiteralPath 'D:\\Data\\25_ACE\\editor'\n$env:EDITOR_PUBLIC_URL = 'http://127.0.0.1:${Number(frontendPort)}'\npython -m uvicorn backend.app.main:app --host 127.0.0.1 --port ${Number(backendPort)} --workers 1`
    : ''
  const frontend = valid
    ? `Set-Location -LiteralPath 'D:\\Data\\25_ACE\\editor\\frontend\\app\\editor'\n$env:EDITOR_BACKEND_URL = 'http://127.0.0.1:${Number(backendPort)}'\nbun run dev --hostname 127.0.0.1 --port ${Number(frontendPort)}`
    : ''
  return (
    <Card>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-heading-small">Launch Configuration</h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setBackendPort('18449')
            setFrontendPort('3003')
          }}
        >
          Reset configuration
        </Button>
      </div>
      <p className="text-body-small text-(--color-text-secondary) mb-4">
        Local PowerShell commands for an installed Editor checkout. Configure required backend
        environment variables in the launching process first; the frontend loads its existing .env
        files. Commands are previews and do not start or replace running services.
      </p>
      <div className="grid md:grid-cols-4 gap-4 mb-4">
        <label>
          Host
          <Input value="127.0.0.1" readOnly />
        </label>
        <label>
          Backend port
          <Input
            aria-label="Backend port"
            type="number"
            min={1}
            max={65535}
            value={backendPort}
            onChange={(e) => setBackendPort(e.target.value)}
          />
        </label>
        <label>
          Frontend port
          <Input
            aria-label="Frontend port"
            type="number"
            min={1}
            max={65535}
            value={frontendPort}
            onChange={(e) => setFrontendPort(e.target.value)}
          />
        </label>
        <label>
          Workers
          <Input type="number" value={1} readOnly />
        </label>
      </div>
      <p className="text-body-small mb-4">
        One backend worker preserves ownership of active in-memory design jobs. Keep
        EDITOR_PLATFORM_DATA_DIR and existing provider keys in the server environment. Database
        configuration remains there; this page does not change it.
      </p>
      {!valid && <p role="alert">Use distinct ports between 1 and 65535.</p>}
      <div className="space-y-4">
        {[
          { label: 'backend', text: backend },
          { label: 'frontend', text: frontend },
        ].map((command) => (
          <div key={command.label}>
            <CopyCommand
              label={`Copy ${command.label} command`}
              text={command.text}
              disabled={!valid}
            />
            <pre
              data-testid={`${command.label}-command`}
              className="mt-2 p-4 rounded-lg bg-(--color-background-secondary) overflow-x-auto text-body-small"
            >
              {command.text || 'Invalid port configuration'}
            </pre>
          </div>
        ))}
      </div>
    </Card>
  )
}
