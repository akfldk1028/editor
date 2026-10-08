import type { LawAnalysis } from '../api/analyze'
import { buildableSummary, envelopeRows, regulationRows, type SetbackRow } from '../lib/setbacks'
import { formatArea } from '../lib/summary'
import { Stat } from './Stat'

/** 이격선: the distances as numbers — the drawn lines stay on the site map. */
export function SetbacksTab({ analysis }: { analysis: LawAnalysis }) {
  const rows = regulationRows(analysis)
  const envelope = envelopeRows(analysis.setback_lines?.sunlight_envelope)
  const buildable = buildableSummary(analysis)
  const ratio = buildable.ratioPct !== null ? `대지면적의 ${buildable.ratioPct.toLocaleString('ko-KR', { maximumFractionDigits: 1 })}%` : '이격선 안 영역이 계산되지 않았어요'

  return (
    <div className="law-setbacks">
      <div className="law-stats">
        <Stat label="건축가능영역 (이격선 안)" note={ratio} value={formatArea(buildable.areaM2)} />
        <Stat label="그린 선" note={buildable.missing.length ? `없는 선: ${buildable.missing.join(' · ')}` : null} value={buildable.drawn.join(' · ') || '없음'} />
      </div>
      <Rows rows={rows} title="규제 거리" />
      {envelope.length > 0 && <Rows rows={envelope} title="정북 일조 사선 (시행령 §86)" />}
      <p className="law-sub">선의 형상은 대지 지도에서 확인하세요 — 여기는 수치만 보여요.</p>
    </div>
  )
}

function Rows({ title, rows }: { title: string; rows: SetbackRow[] }) {
  return (
    <section aria-label={title} className="law-card">
      <h2>{title}</h2>
      {rows.length === 0 ? <p className="law-sub">항목이 없어요.</p> : (
        <table className="law-table">
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th scope="row">{row.name}</th>
                <td>
                  <div>
                    <b>{row.value}</b>
                    {row.note && <span>{row.note}</span>}
                    {row.basis && <small>{row.basis}</small>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
