import { describe, it, expect, beforeEach } from 'bun:test'
import { useToolApprovalStore } from './tool-approval.store'
import type { ToolApproval } from './tool-approval.types'

function makeApproval(overrides: Partial<ToolApproval> = {}): ToolApproval {
  return {
    id: `test-${Date.now()}-${Math.random()}`,
    toolName: 'test_tool',
    args: '{}',
    icon: 'generic',
    source: 'agent',
    timestamp: new Date().toISOString(),
    status: 'pending',
    ...overrides,
  }
}

describe('useToolApprovalStore', () => {
  beforeEach(() => {
    const store = useToolApprovalStore.getState()
    store.clearQueue()
    store.clearCache()
  })

  it('enqueues an approval', () => {
    const approval = makeApproval({ id: 'a1' })
    const result = useToolApprovalStore.getState().enqueue(approval)
    expect(result).toBe('queued')
    expect(useToolApprovalStore.getState().queue).toHaveLength(1)
  })

  it('peek returns first in queue (FIFO)', () => {
    const a = makeApproval({ id: 'first' })
    const b = makeApproval({ id: 'second' })
    useToolApprovalStore.getState().enqueue(a)
    useToolApprovalStore.getState().enqueue(b)
    expect(useToolApprovalStore.getState().peek()?.id).toBe('first')
  })

  it('approve removes from queue', () => {
    const a = makeApproval({ id: 'a1' })
    useToolApprovalStore.getState().enqueue(a)
    const result = useToolApprovalStore.getState().approve('a1')
    expect(result?.status).toBe('approved')
    expect(useToolApprovalStore.getState().queue).toHaveLength(0)
  })

  it('reject removes from queue', () => {
    const a = makeApproval({ id: 'r1' })
    useToolApprovalStore.getState().enqueue(a)
    const result = useToolApprovalStore.getState().reject('r1')
    expect(result?.status).toBe('rejected')
    expect(useToolApprovalStore.getState().queue).toHaveLength(0)
  })

  it('approveAlways adds to cache and auto-approves subsequent', () => {
    const a = makeApproval({ id: 'aa1', toolName: 'cached_tool' })
    useToolApprovalStore.getState().enqueue(a)
    useToolApprovalStore.getState().approveAlways('aa1')

    // Cache should contain the tool
    expect(useToolApprovalStore.getState().alwaysAllowCache.has('cached_tool')).toBe(true)

    // Next enqueue should auto-approve
    const b = makeApproval({ id: 'aa2', toolName: 'cached_tool' })
    const result = useToolApprovalStore.getState().enqueue(b)
    expect(result).toBe('auto-approved')
    expect(useToolApprovalStore.getState().queue).toHaveLength(0)
  })

  it('clearCache removes auto-approve entries', () => {
    const a = makeApproval({ id: 'cc1', toolName: 'tool_x' })
    useToolApprovalStore.getState().enqueue(a)
    useToolApprovalStore.getState().approveAlways('cc1')
    useToolApprovalStore.getState().clearCache()
    expect(useToolApprovalStore.getState().alwaysAllowCache.size).toBe(0)
  })
})
