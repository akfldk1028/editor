import type { RunLaw } from '@/lib/orchestrator-runs/types'

import type { LawAnalysis } from '../api/analyze'
import { capStat, formatArea, formatWon, restrictionsWith, settledBadge, summarize } from '../lib/summary'
import { Stat } from './Stat'

/** 요약: 용도지역, 건폐율/용적률 상한 (the Law Agent's when it set them), 대지면적, 심사 상태, 제한 목록. */
export function SummaryTab({ analysis, limits }: { analysis: LawAnalysis; limits: RunLaw | null }) {
  const summary = summarize(analysis)
  const bcr = capStat(summary.bcr, limits?.bcr_pct ?? null, limits?.articles.bcr ?? null, limits?.policy_id ?? null)
  const far = capStat(summary.far, limits?.far_pct ?? null, limits?.articles.far ?? null, limits?.policy_id ?? null)
  // Both caps set by the Law Agent: "증거 부족" would misread as doubt about them; the badge says what is really left.
  const assessment = settledBadge(summary.assessment, analysis.assessment, limits?.bcr_pct != null && limits?.far_pct != null)
  const restrictions = restrictionsWith(summary.restrictions, limits?.bcr_pct ?? null, limits?.far_pct ?? null, limits?.policy_id ?? null)
  const landNote = [
    summary.landCategory ? `지목 ${summary.landCategory}` : null,
    summary.officialPrice !== null ? `공시지가 ${formatWon(summary.officialPrice)}` : null,
  ].filter(Boolean).join(' · ')

  return (
    <div className="law-summary">
      <section aria-label="용도지역" className="law-card">
        <h2>용도지역 {summary.zones.length > 1 && <small>{summary.zones.length}개 걸침</small>}</h2>
        <ul className="law-chips">
          {summary.zones.map((zone) => <li key={zone}>{zone}</li>)}
          {summary.zones.length === 0 && <li data-kind="muted">용도지역 —</li>}
        </ul>
        {summary.zoneAreas.length > 1 && (
          <dl className="law-kv">
            {summary.zoneAreas.map(({ zone, areaM2 }) => (
              <div key={zone}><dt>{zone}</dt><dd>{formatArea(areaM2)}</dd></div>
            ))}
          </dl>
        )}
        {summary.overlapArticle && <p className="law-sub">둘 이상의 용도지역: 면적 가중 적용 — {summary.overlapArticle}</p>}
        {summary.otherZones.length > 0 && <p className="law-sub">그 밖의 지역·지구: {summary.otherZones.join(' · ')}</p>}
      </section>

      <div className="law-stats">
        <Stat basis={bcr.basis} label="건폐율 상한" note={bcr.note} tone={bcr.warn ? 'warn' : undefined} value={bcr.value} />
        <Stat basis={far.basis} label="용적률 상한" note={far.note} tone={far.warn ? 'warn' : undefined} value={far.value} />
        {limits?.max_floors !== null && limits?.max_floors !== undefined && (
          <Stat basis={limits.policy_id ? `Law Agent · 지구단위 정책 ${limits.policy_id}` : 'Law Agent'} label="최고 층수" value={`${limits.max_floors}층`} />
        )}
        <Stat label="대지면적" note={landNote || null} value={formatArea(summary.areaM2)} />
      </div>

      <section aria-label="심사 상태" className="law-card">
        <h2>
          심사 상태 <span className="law-badge" data-tone={assessment.tone}>{assessment.label}</span>
          {summary.assessmentDate && <small>기준일 {summary.assessmentDate}</small>}
        </h2>
        {assessment.detail.length > 0 && (
          <ul className="law-list">{assessment.detail.map((line) => <li key={line}>{line}</li>)}</ul>
        )}
      </section>

      <section aria-label="제한 목록" className="law-card">
        <h2>제한 목록 <small>{restrictions.length}</small></h2>
        {restrictions.length > 0
          ? <ol className="law-list">{restrictions.map((line) => <li key={line}>{line}</li>)}</ol>
          : <p className="law-sub">제한 항목이 없어요.</p>}
      </section>
    </div>
  )
}
