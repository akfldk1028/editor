'use client'

import { useEffect, useRef, useState } from 'react'
import type { ProjectBinding } from './projects'
import type { RunSummary } from './runs'
import { object, type SpecialistRequest } from './specialist-review'
import { loadFollowupMaterial, prepareFollowup, type FollowupAnswers, type FollowupMaterial } from './followup-review'

const emptyAnswers: FollowupAnswers = { domain: '', proposal: '', sourceId: '', brief: '', operationalType: '', functionalType: '' }

export function FollowupReviewDraft({ project, run, disabled, onPrepared, onDraftChanged }: {
  project: ProjectBinding; run: RunSummary; disabled: boolean; onPrepared: (request: SpecialistRequest) => void; onDraftChanged: () => void
}) {
  const [material, setMaterial] = useState<FollowupMaterial | null>(null)
  const [selected, setSelected] = useState(0)
  const [answers, setAnswers] = useState(emptyAnswers)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [prepared, setPrepared] = useState(false)
  const pending = useRef<AbortController | null>(null)
  useEffect(() => () => pending.current?.abort(), [])
  function select(index: number, source = material) {
    setSelected(index); setPrepared(false)
    onDraftChanged()
    const args = source?.request.specialist_reviews[index]?.args.request
    setAnswers({ ...emptyAnswers,
      domain: object(args) && typeof args.declared_domain === 'string' ? args.declared_domain : '',
      brief: object(args) && object(args.intent) && typeof args.intent.brief === 'string' ? args.intent.brief : '',
      operationalType: object(args) && typeof args.operational_type === 'string' ? args.operational_type : '',
      functionalType: object(args) && typeof args.functional_type === 'string' ? args.functional_type : '',
    })
  }
  async function load() {
    if (pending.current) return
    const controller = new AbortController()
    pending.current = controller; setBusy(true); setError('')
    try {
      const result = await loadFollowupMaterial(project, run, controller.signal)
      if (!controller.signal.aborted) { setMaterial(result); select(0, result) }
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '후속 검토를 불러오지 못했습니다.')
    } finally {
      pending.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  function update(key: keyof FollowupAnswers, value: string) {
    setAnswers(previous => ({ ...previous, [key]: value })); setPrepared(false)
    onDraftChanged()
  }
  const item = material?.request.specialist_reviews[selected]
  const original = item && object(item.args.request) ? item.args.request : null
  const sources = original && Array.isArray(original.sources) ? original.sources.filter(source => object(source) && typeof source.id === 'string') : []
  const reviews = material?.reviews.filter(review => review.agent === item?.agent && review.tool === item?.tool) || []
  const field = 'mt-1 block w-full rounded border border-(--color-border-default) bg-(--color-surface-card) p-2'
  return <div data-testid="followup-review-draft" className="space-y-3 rounded border border-(--color-border-default) p-3">
    <h3 className="font-medium">담당 에이전트와 설계 이어가기</h3>
    <p className="text-sm">미정인 조건도 대화의 출발점입니다. 담당 에이전트의 검토 내용을 보고 방향을 제안하면 다음 검토 요청을 준비합니다.</p>
    {!material && <button type="button" disabled={disabled || busy} className="underline" onClick={() => void load()}>{busy ? '원본 요청 확인 중…' : '이 실행에서 대화 이어가기'}</button>}
    {material && <fieldset disabled={disabled || busy} className="space-y-3">
      <label className="block">대화할 담당 에이전트<select className={field} value={selected} onChange={event => select(Number(event.target.value))}>
        {material.request.specialist_reviews.map((entry, index) => <option key={`${entry.agent}:${entry.tool}`} value={index}>{entry.agent} · {entry.tool}</option>)}
      </select></label>
      {reviews.map(review => <details key={review.task_id} open>
        <summary>담당 에이전트가 남긴 검토 사항 · {review.state}</summary>
        {review.needs.length ? <ul className="ml-5 list-disc text-sm">{review.needs.slice(0, 8).map((need, index) => <li key={index}>{need}</li>)}</ul> : <p className="text-sm">구조화된 추가 질문이 없습니다. 아래 대화 기록에서 소유자의 응답을 함께 확인할 수 있습니다.</p>}
        {review.needs.length > 8 && <details><summary>나머지 검토 사항 {review.needs.length - 8}개</summary><ul className="ml-5 list-disc text-sm">{review.needs.slice(8).map((need, index) => <li key={index}>{need}</li>)}</ul></details>}
        {review.needs_truncated && <p className="text-sm">일부 항목은 표시 범위를 넘거나 비공개 필드가 있어 생략되었습니다.</p>}
      </details>)}
      {item?.tool === 'domain_review' && <>
        <label className="block">검토할 용도·운영 방향<input className={field} value={answers.domain} maxLength={200} onChange={event => update('domain', event.target.value)} placeholder="예: 공공 업무시설의 방문객·직원 운영" /></label>
        <label className="block">함께 검토할 제안·조건<textarea className={field} rows={4} value={answers.proposal} maxLength={20000} onChange={event => update('proposal', event.target.value)} placeholder="한 줄에 한 가지 제안을 적으세요. 확정되지 않은 방향도 제안할 수 있습니다." /></label>
        <label className="block">제안과 연결할 기존 자료<select className={field} value={answers.sourceId} onChange={event => update('sourceId', event.target.value)}>
          <option value="">아직 자료 연결 없음 · 제안으로 검토</option>
          {sources.map(source => <option key={String(source.id)} value={String(source.id)}>{String(source.id)}</option>)}
        </select></label>
        <p className="text-sm">새 조건은 사용자 제안으로 전달됩니다. 기존 자료의 검증 상태나 승인 여부는 바꾸지 않습니다.</p>
      </>}
      {item?.tool === 'interior_review' && <label className="block">인테리어 방향·다음 질문<textarea className={field} rows={5} value={answers.brief} maxLength={20000} onChange={event => update('brief', event.target.value)} /></label>}
      {item?.tool === 'systems_requirements' && <>
        <p className="text-sm">설비 부하를 확정하기 전, Systems 소유자의 용도별 설계 조건을 탐색합니다. 비워 두면 지원하는 전체 용도를 요청합니다.</p>
        <label className="block">운영 용도 코드 (선택)<input className={field} value={answers.operationalType} maxLength={200} onChange={event => update('operationalType', event.target.value)} /></label>
        <label className="block">공간 기능 코드 (선택)<input className={field} value={answers.functionalType} maxLength={200} onChange={event => update('functionalType', event.target.value)} /></label>
      </>}
      <button type="button" className="rounded border border-(--color-border-default) p-2" onClick={() => {
        if (!item) return
        try { onPrepared(prepareFollowup(item, answers, run.run_id)); setPrepared(true); setError('') }
        catch (e) { setError(e instanceof Error ? e.message : '후속 요청을 준비하지 못했습니다.') }
      }}>후속 검토 요청 준비</button>
      {prepared && <p role="status">아래 미리보기에서 요청을 확인한 뒤 담당 에이전트 검토를 실행하세요.</p>}
    </fieldset>}
    {error && <p role="alert" className="text-red-500">{error}</p>}
  </div>
}
