import type { SystemStatus } from '../api/status'
import { groupServices } from '../lib/presentation'
import { ServiceRow } from './ServiceRow'

const COLUMNS = ['', '서비스', '상태', '포트', '버전', '가동 시간', '마지막 확인']

/** The registry's services grouped 에디터 / 오케스트레이터 / 에이전트 / 인프라, one row each. */
export function StatusTable({ status, stale }: { status: SystemStatus; stale: boolean }) {
  const now = Date.now()
  const groups = groupServices(status.services)
  return (
    <div className="system-groups">
      {status.orchestrator.state !== 'up' && (
        <p className="system-banner" role="status">
          오케스트레이터가 응답하지 않아요 — 에이전트 상태는 직접 확인한 값이고, 검토 실행은 오케스트레이터가 켜진 뒤에 가능해요.
        </p>
      )}
      {stale && <p className="system-banner" data-kind="stale" role="status">상태 확인이 지연되고 있어요 — 마지막으로 받은 값이에요.</p>}
      {groups.map((group) => (
        <section aria-labelledby={`system-group-${group.kind}`} className="system-group" key={group.kind}>
          <h2 id={`system-group-${group.kind}`}>
            {group.title}
            <small>{group.up}/{group.rows.length} 가동</small>
          </h2>
          <ul className="system-rows">
            <li aria-hidden="true" className="system-head">
              {COLUMNS.map((column, index) => <span key={index}>{column}</span>)}
            </li>
            {group.rows.map((row) => <ServiceRow key={row.id} now={now} row={row} />)}
          </ul>
        </section>
      ))}
    </div>
  )
}
