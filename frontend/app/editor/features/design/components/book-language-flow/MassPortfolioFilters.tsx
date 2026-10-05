import type { MassPortfolioCard, MassStageName } from '../../lib/mass-portfolio-types'
import type { MassPortfolioFilters as FilterState } from './mass-portfolio-adapter'

export function MassPortfolioFilters({ cards, value, onChange }: {
  cards: readonly MassPortfolioCard[]
  value: FilterState
  onChange: (value: FilterState) => void
}) {
  const update = (key: keyof FilterState, next: string) => onChange({ ...value, [key]: next })
  const programs = Array.from(new Set(cards.map((card) => card.program).filter(Boolean))).sort()
  return (
    <div className="mass-portfolio-filters" aria-label="MASS portfolio filters">
      <Select label="Program" value={value.program} values={programs} onChange={(v) => update('program', v)} />
      <Select label="Overall status" value={value.overallStatus} values={['selected', 'legal_pass', 'failed', 'not_evaluated']} onChange={(v) => update('overallStatus', v)} />
      <Select label="Gate" value={value.gate} values={['geometry', 'law', 'capacity', 'parking', 'program', 'vlm', 'selection']} onChange={(v) => update('gate', v as MassStageName)} />
      <Select label="Gate status" value={value.gateStatus} values={['pass', 'failed', 'not_evaluated']} onChange={(v) => update('gateStatus', v)} />
    </div>
  )
}

function Select({ label, value, values, onChange }: { label: string; value: string; values: string[]; onChange: (value: string) => void }) {
  return <label><span>{label}</span><select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}><option value="">ALL</option>{values.map((item) => <option key={item} value={item}>{item.replace('_', ' ').toUpperCase()}</option>)}</select></label>
}
