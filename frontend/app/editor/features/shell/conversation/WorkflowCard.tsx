import { agentLabel } from '@/lib/orchestrator-runs/labels'
import { phaseLabel, protocolLabel, stepOrder, stepStatus, stepTitle, type Workflow, workflowStatus } from '@/lib/design-conversation/workflow'

/**
 * One multi-owner workflow as a card in the conversation: how the owners worked together, and each step with its
 * owner, what it did and where it stands — in the user's words, never the Orchestrator's step ids or codes.
 * The flow (협업 artifact) draws the same record.
 */
export function WorkflowCard({ flow }: { flow: Workflow }) {
  const status = workflowStatus(flow)
  const order = stepOrder(flow)
  return <details className="conversation-artifact conversation-workflow" open={flow.status === 'running'}>
    <summary>
      <strong>함께 작업 · {protocolLabel(flow.protocol)}</strong><span>{agentLabel('orchestrator')}</span>
      <span className="conversation-artifact-status" data-tone={status.tone}>{status.label}</span>
    </summary>
    <ol className="conversation-workflow-steps">
      {order.map((id) => {
        const step = flow.steps[id]!
        const state = stepStatus(step.status, step.code)
        return <li key={id} data-state={state.tone}>
          <span className="conversation-workflow-owner">{agentLabel(step.owner)}</span>
          <span className="conversation-workflow-title">{stepTitle(step)}<small>{phaseLabel(step.phase)}</small></span>
          <span className="conversation-artifact-status" data-tone={state.tone === 'running' ? 'neutral' : state.tone}>{state.label}</span>
          {step.message && <p className="conversation-workflow-message">{step.message}</p>}
        </li>
      })}
    </ol>
  </details>
}
