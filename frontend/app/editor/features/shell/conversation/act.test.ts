import { expect, test } from 'bun:test'
import { act } from './act'
import { onCommand } from '@/lib/orchestrator-runs/commands'
import { setConversationSite } from '@/lib/orchestrator-runs/site-context'
import type { ShellApi } from '../artifact-types'

test('legal review opens Law for the selected site without a project or site-card command', () => {
  const opened: unknown[] = []
  const commands: unknown[] = []
  const stop = onCommand((command) => commands.push(command))
  const shell: ShellApi = { openArtifact: (...args) => { opened.push(args) }, closeArtifact() {}, setTab() {}, setTitle() {} }
  setConversationSite({ pnu: 'selected-parcel', address: 'selected address' })
  try {
    act({ label: '법규 검토', command: { kind: 'start-review', goal: 'limits' } }, shell)
    expect(opened).toEqual([['law', { pnu: 'selected-parcel', address: 'selected address', tab: 'review' }]])
    expect(commands).toEqual([])
    act({ label: '법규 검토', artifact: 'law', params: { pnu: 'captured-parcel', tab: 'review' } }, shell)
    expect(opened[1]).toEqual(['law', { pnu: 'captured-parcel', tab: 'review' }])
  } finally {
    stop()
    setConversationSite(null)
  }
})
