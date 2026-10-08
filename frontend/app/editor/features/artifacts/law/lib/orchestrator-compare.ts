/** The Orchestrator's Law numbers beside the editor's own 요약 numbers, row by row. Pure. */
import type { RunLaw } from '@/lib/orchestrator-runs/types'

import type { Cap, Summary } from './summary'
import { formatArea } from './summary'

export interface CompareRow {
  label: string
  /** What the Orchestrator's Law agent returned. */
  run: string
  /** What the editor's own analysis (요약 탭) shows. */
  editor: string
  /** true: the two differ; false: they agree; null: not comparable (one side has no value). */
  differs: boolean | null
}

const pct = (value: number) => `${value.toLocaleString('ko-KR', { maximumFractionDigits: 2 })}%`
/** Areas within 0.5% are the same parcel measured by two sources (cadastre vs. ledger). */
const AREA_TOLERANCE = 0.005
const PCT_TOLERANCE = 0.05

function area(run: number | null, editor: number | null): CompareRow {
  const differs = run === null || editor === null ? null : Math.abs(run - editor) > Math.max(run, editor) * AREA_TOLERANCE
  return { label: '대지면적', run: run === null ? '—' : formatArea(run), editor: editor === null ? '—' : formatArea(editor), differs }
}

/** The editor's cap is the ordinance limit when known; otherwise it is 미확정 (the statutory ceiling only as context). */
function cap(label: string, run: number | null, editor: Cap): CompareRow {
  const editorText = editor.limit !== null ? pct(editor.limit) : editor.ceiling !== null ? `미확정 (법정 상한 ${pct(editor.ceiling)})` : '미확정'
  const differs = run === null ? null : editor.limit === null ? true : Math.abs(run - editor.limit) > PCT_TOLERANCE
  return { label, run: run === null ? '—' : pct(run), editor: editorText, differs }
}

export function compareLaw(law: RunLaw | null, editor: Summary | null): CompareRow[] {
  const floors = law?.max_floors ?? null
  return [
    area(law?.site_area_m2 ?? null, editor?.areaM2 ?? null),
    cap('건폐율 상한', law?.bcr_pct ?? null, editor?.bcr ?? { limit: null, ceiling: null, status: null, article: '' }),
    cap('용적률 상한', law?.far_pct ?? null, editor?.far ?? { limit: null, ceiling: null, status: null, article: '' }),
    { label: '최고 층수', run: floors === null ? '—' : `${floors}층`, editor: '—', differs: null },
  ]
}

/** Count of rows whose values differ, for the tab's note. */
export const differingRows = (rows: readonly CompareRow[]) => rows.filter((row) => row.differs === true).length
