import type { ReactNode } from 'react'

import type { ServiceStatus } from '../api/status'
import { downHint, formatClock, formatUptime, stateLabel } from '../lib/presentation'

/** One cell; the label is read on narrow layouts where the header row is gone. */
function Cell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="system-cell">
      <small className="system-cell-label">{label}</small>
      <span>{children}</span>
    </span>
  )
}

export function ServiceRow({ row, now }: { row: ServiceStatus; now: number }) {
  const hint = downHint(row)
  const connection = row.orchestrator?.connection_status
  return (
    <li className="system-row" data-state={row.state}>
      <span aria-hidden="true" className="system-dot" />
      <span className="system-name">
        <b title={row.notes || undefined}>{row.label}</b>
        {row.label !== row.id && <code>{row.id}</code>}
      </span>
      <Cell label="상태">
        {stateLabel[row.state]}
        {connection && <small className="system-sub"> · 오케스트레이터: {connection}</small>}
        {row.managed_by && <small className="system-sub"> · host pid {row.managed_by.pid}</small>}
      </Cell>
      <Cell label="포트">{row.port ?? '—'}</Cell>
      <Cell label="버전"><span className="system-version" title={row.version ?? undefined}>{row.version ?? '—'}</span></Cell>
      <Cell label="가동 시간">{formatUptime(row.started_at, now)}</Cell>
      <Cell label="마지막 확인">
        {formatClock(row.checked_at, now)}
        {row.latency_ms !== null && <small className="system-sub"> · {row.latency_ms}ms</small>}
      </Cell>
      {hint && <p className="system-hint">{hint}</p>}
    </li>
  )
}
