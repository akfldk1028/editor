import type { ConversationArtifact } from '@/lib/design-conversation/types'
import { confirmationFor } from '@/lib/design-conversation/confirmation'
import { artifactStatus } from '@/lib/design-conversation/artifact-status'
import { type RequirementsSheet, requirementsSheet } from '@/lib/agents/requirement/lib/sheet'
import { agentLabel } from '@/lib/orchestrator-runs/labels'

function Value({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span>—</span>
  if (typeof value !== 'object') return <span>{typeof value === 'boolean' ? (value ? '예' : '아니요') : String(value)}</span>
  if (depth > 3) return <details><summary>상세 내용</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
  if (Array.isArray(value)) return <ul>{value.map((item, index) => <li key={index}><Value value={item} depth={depth + 1} /></li>)}</ul>
  return <dl>{Object.entries(value).map(([key, item]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd><Value value={item} depth={depth + 1} /></dd></div>)}</dl>
}

/**
 * The Requirement Agent's brief as one card that fills in while the user talks: each field in the user's
 * words, its value or "아직 없음" — never the owner's field ids, status codes or empty JSON.
 */
function RequirementsCard({ sheet }: { sheet: RequirementsSheet }) {
  return <details className="conversation-artifact conversation-sheet" open>
    <summary>
      <strong>요구사항</strong><span>{agentLabel('requirement')}</span>
      <span className="conversation-artifact-status" data-tone={sheet.stale ? 'attention' : sheet.filled === sheet.total ? 'confirmed' : 'neutral'}>
        {sheet.stale ? '이전 조건 기준' : `${sheet.filled}/${sheet.total} 채워짐`}
      </span>
    </summary>
    <dl>
      {sheet.fields.map((field) => <div key={field.key} data-filled={field.filled ? 'true' : 'false'}>
        <dt>{field.label}</dt>
        <dd>{field.filled ? <Value value={field.value} /> : <span className="conversation-sheet-empty">아직 없음 · 대화로 채워져요</span>}</dd>
      </div>)}
    </dl>
  </details>
}

export function ConversationArtifacts({ artifacts, onConfirm, disabled = false }: { artifacts: ConversationArtifact[]; onConfirm?: (artifact: ConversationArtifact) => void; disabled?: boolean }) {
  if (!artifacts.length) return null
  const { sheet, rest } = requirementsSheet(artifacts)
  return <section className="conversation-artifacts" aria-label="대화 결과">
    {sheet && <RequirementsCard sheet={sheet} />}
    {rest.map((artifact) => {
      const confirmation = confirmationFor(artifact)
      const status = artifactStatus(artifact.status)
      const { proposed_intent, kind: _kind, ...evidence } = artifact.data
      return <details className="conversation-artifact" key={artifact.id} open={!!confirmation}>
        <summary><strong>{artifact.title}</strong><span>{agentLabel(artifact.owner)}</span><span className="conversation-artifact-status" data-tone={status.tone}>{status.label}</span></summary>
        {confirmation ? <>
          <p className="conversation-intent-label">검토할 설계 의도</p>
          <Value value={proposed_intent} />
          <details className="conversation-review-evidence"><summary>검토 근거</summary><Value value={evidence} /></details>
        </> : <Value value={artifact.data} />}
        {onConfirm && confirmation && <button className="agent-answer" data-primary="true" disabled={disabled} onClick={() => onConfirm(artifact)} type="button">변경된 조건으로 설계 의도 확인</button>}
      </details>
    })}
  </section>
}
