import type { ConversationArtifact } from '@/lib/design-conversation/types'
import { confirmationFor } from '@/lib/design-conversation/confirmation'
import { artifactStatus } from '@/lib/design-conversation/artifact-status'
import { agentLabel } from '@/lib/orchestrator-runs/labels'

function Value({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span>—</span>
  if (typeof value !== 'object') return <span>{typeof value === 'boolean' ? (value ? '예' : '아니요') : String(value)}</span>
  if (depth > 3) return <details><summary>상세 내용</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
  if (Array.isArray(value)) return <ul>{value.map((item, index) => <li key={index}><Value value={item} depth={depth + 1} /></li>)}</ul>
  return <dl>{Object.entries(value).map(([key, item]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd><Value value={item} depth={depth + 1} /></dd></div>)}</dl>
}

export function ConversationArtifacts({ artifacts, onConfirm, disabled = false }: { artifacts: ConversationArtifact[]; onConfirm?: (artifact: ConversationArtifact) => void; disabled?: boolean }) {
  if (!artifacts.length) return null
  return <section className="conversation-artifacts" aria-label="대화 결과">
    {artifacts.map((artifact) => {
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
