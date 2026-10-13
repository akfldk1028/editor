import type { TurnStep } from '@/lib/ledger'

/** One line per agent asked: who, what (tools named in words), how many times, and done, asking or failed. */
export function StepList({ steps }: { steps: TurnStep[] }) {
  if (!steps.length) return null
  return <ul className="agent-step-list">
    {steps.map((step) => <li data-failed={step.failed ? 'true' : 'false'} data-running={step.running ? 'true' : 'false'} key={step.agent}>
      <b>{step.label}</b>
      {step.tools.length > 0 && <span>{step.tools.slice(0, 3).join(', ')}{step.tools.length > 3 ? ' …' : ''}</span>}
      <small>{step.running ? '묻는 중' : step.failed ? `${step.calls}번 · 실패 있음` : `${step.calls}번 ✓`}</small>
    </li>)}
  </ul>
}

/** A finished reply's steps, folded under one line: "에이전트 3곳에 13번 물어봤어요 · Law Agent, Site Agent, …". */
export function AskedAgents({ steps }: { steps: TurnStep[] }) {
  if (!steps.length) return null
  const calls = steps.reduce((sum, step) => sum + step.calls, 0)
  return <details className="agent-asked">
    <summary>에이전트 {steps.length}곳에 {calls}번 물어봤어요 · {steps.map((step) => step.label).join(', ')}</summary>
    <StepList steps={steps} />
  </details>
}
