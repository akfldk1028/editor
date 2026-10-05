import { useEffect, useRef, useState } from 'react'
import { Button, Card } from '@/elements/workspace'
import type { McpClient } from './api/mcp-client'

export function McpResources({ connection }: { connection?: McpClient }) {
  const [resources, setResources] = useState<Array<{ uri: string; name?: string }>>([])
  const [output, setOutput] = useState('')
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  useEffect(() => () => { generation.current++ }, [connection])
  const perform = async (uri?: string) => {
    if (!connection?.isConnected) return
    const token = ++generation.current
    setBusy(true)
    try {
      const result = uri ? await connection.readResource(uri) : await connection.listResources()
      if (token !== generation.current) return
      if (result.type === 'operation_error') setOutput(result.error || 'Resource operation failed')
      else if (uri) setOutput(JSON.stringify(result.data, null, 2))
      else {
        const rows = (result.data as { resources?: Array<{ uri: string; name?: string }> })?.resources
        setResources(Array.isArray(rows) ? rows : [])
        setOutput(Array.isArray(rows) && rows.length ? '' : 'No resources available')
      }
    } finally { if (token === generation.current) setBusy(false) }
  }
  return <Card>
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-heading-small">Resources</h2>
      <Button disabled={!connection?.isConnected || busy} onClick={() => void perform()}>List Resources</Button>
    </div>
    <div className="flex flex-wrap gap-2">{resources.map(resource =>
      <Button key={resource.uri} disabled={busy || !connection?.isConnected} onClick={() => void perform(resource.uri)}>
        {resource.name || resource.uri}
      </Button>)}</div>
    {output && <pre data-testid="mcp-resource-output" className="overflow-auto mt-3 max-h-64">{output}</pre>}
  </Card>
}
