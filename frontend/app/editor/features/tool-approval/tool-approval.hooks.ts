import { useCallback } from 'react'
import { useToolApprovalStore } from './tool-approval.store'
import type { ToolApproval } from './tool-approval.types'

/**
 * Hook that bridges the tool approval store with the WebSocket input_response.
 * Pass in the WS sendInput callback from the Playground.
 */
export function useToolApproval(sendResponse?: (response: string) => void) {
  const pending = useToolApprovalStore((s) => s.peek())
  const queueLength = useToolApprovalStore((s) => s.queue.length)
  const approve = useToolApprovalStore((s) => s.approve)
  const approveAlways = useToolApprovalStore((s) => s.approveAlways)
  const reject = useToolApprovalStore((s) => s.reject)

  const handleApprove = useCallback(
    (id: string) => {
      const result = approve(id)
      if (result) sendResponse?.('APPROVE')
    },
    [approve, sendResponse],
  )

  const handleApproveAlways = useCallback(
    (id: string) => {
      const result = approveAlways(id)
      if (result) sendResponse?.('APPROVE')
    },
    [approveAlways, sendResponse],
  )

  const handleReject = useCallback(
    (id: string) => {
      const result = reject(id)
      if (result) sendResponse?.('REJECT')
    },
    [reject, sendResponse],
  )

  return {
    pending,
    queueLength,
    handleApprove,
    handleApproveAlways,
    handleReject,
  }
}

/**
 * Auto-approve handler for the execution store integration.
 * Returns true if the tool was auto-approved (sendResponse should be called).
 */
export function tryAutoApprove(approval: ToolApproval): boolean {
  const result = useToolApprovalStore.getState().enqueue(approval)
  return result === 'auto-approved'
}
