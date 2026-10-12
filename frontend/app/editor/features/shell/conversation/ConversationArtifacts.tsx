import type { ConversationArtifact } from '@/lib/design-conversation/types'
import { confirmationFor } from '@/lib/design-conversation/confirmation'
import { artifactStatus } from '@/lib/design-conversation/artifact-status'
import { type RequirementsSheet, requirementsSheet } from '@/lib/agents/requirement/lib/sheet'
import { agentLabel } from '@/lib/orchestrator-runs/labels'

/** Field names any owner's artifact may carry, in the user's words; unknown keys keep their name. */
const FIELD_LABELS: Record<string, string> = {
  value: '값', building_type: '용도', pnu: '지번', address: '주소', site_area: '대지면적', site_area_m2: '대지면적', floor_area: '연면적',
  floor_area_m2: '연면적', gross_floor_area_m2: '연면적', floors: '층수', storeys: '층수', budget: '예산', schedule: '일정', operator: '운영 주체',
  capacity: '정원', description: '설명', summary: '요약', status: '상태', reason: '이유', notes: '메모', title: '제목', name: '이름',
  uses: '용도 구성', areas: '면적', area_m2: '면적', units: '세대·호수', parking: '주차', height_m: '높이', bcr_pct: '건폐율', far_pct: '용적률',
  assumptions: '가정', constraints: '제약', priorities: '우선순위', unknowns: '미확인', must_have: '꼭 필요한 것', nice_to_have: '있으면 좋은 것',
}
const label = (key: string) => FIELD_LABELS[key] ?? key.replaceAll('_', ' ')
const empty = (value: unknown) => value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)
  || (typeof value === 'object' && !Array.isArray(value) && value !== null && Object.keys(value).length === 0)

function Value({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (empty(value)) return <span className="conversation-sheet-empty">아직 없음</span>
  if (typeof value !== 'object') return <span>{typeof value === 'boolean' ? (value ? '예' : '아니요') : String(value)}</span>
  if (depth > 3) return <details><summary>상세 내용</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
  if (Array.isArray(value)) return <ul>{value.map((item, index) => <li key={index}><Value value={item} depth={depth + 1} /></li>)}</ul>
  const entries = Object.entries(value as Record<string, unknown>).filter(([key]) => key !== 'kind')
  // `{value: x}` is an owner's wrapper for a plain field, not a field called "value".
  if (entries.length === 1 && entries[0]![0] === 'value') return <Value value={entries[0]![1]} depth={depth} />
  return <dl>{entries.map(([key, item]) => <div key={key} data-filled={empty(item) ? 'false' : 'true'}><dt>{label(key)}</dt><dd><Value value={item} depth={depth + 1} /></dd></div>)}</dl>
}

/** An owner's artifact title in the user's words: a known id family, else the owner's own title. */
const TITLES: [prefix: string, title: string][] = [['program.', '프로그램'], ['design_intent.', '설계 의도'], ['intent', '설계 의도'], ['requirements.', '요구사항']]
const artifactTitle = (artifact: ConversationArtifact) => TITLES.find(([prefix]) => artifact.id.startsWith(prefix) || artifact.title.startsWith(prefix))?.[1] ?? artifact.title

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
        <summary><strong>{artifactTitle(artifact)}</strong><span>{agentLabel(artifact.owner)}</span><span className="conversation-artifact-status" data-tone={status.tone}>{status.label}</span></summary>
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
