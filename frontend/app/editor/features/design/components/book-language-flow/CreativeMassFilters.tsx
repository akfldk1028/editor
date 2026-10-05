import type { CreativeMassCard } from '../../lib/language-system-types'


export interface CreativeMassFilterState {
  family: string
  capacityBand: string
  storeys: string
  legalStatus: string
}

interface CreativeMassFiltersProps {
  cards: readonly CreativeMassCard[]
  value: CreativeMassFilterState
  onChange: (value: CreativeMassFilterState) => void
}

export function filterCreativeMassCards(
  cards: readonly CreativeMassCard[],
  filters: CreativeMassFilterState,
): CreativeMassCard[] {
  return cards.filter((card) => (
    (!filters.family || card.family === filters.family)
    && (!filters.capacityBand || card.capacityBand === filters.capacityBand)
    && (!filters.storeys || card.storeys === Number(filters.storeys))
    && (!filters.legalStatus || card.legalStatus === filters.legalStatus)
  ))
}

export function CreativeMassFilters({
  cards,
  value,
  onChange,
}: CreativeMassFiltersProps) {
  const choices = {
    family: unique(cards.map((card) => card.family)),
    capacityBand: unique(cards.map((card) => card.capacityBand)),
    storeys: unique(cards.map((card) => String(card.storeys))),
    legalStatus: unique(cards.map((card) => card.legalStatus)),
  }
  const update = (key: keyof CreativeMassFilterState, next: string) => {
    onChange({ ...value, [key]: next })
  }
  return (
    <div className="creative-mass-filters" aria-label="Creative MASS filters">
      <FilterSelect
        label="Family"
        value={value.family}
        choices={choices.family}
        onChange={(next) => update('family', next)}
      />
      <FilterSelect
        label="Capacity band"
        value={value.capacityBand}
        choices={choices.capacityBand}
        onChange={(next) => update('capacityBand', next)}
      />
      <FilterSelect
        label="Storeys"
        value={value.storeys}
        choices={choices.storeys}
        onChange={(next) => update('storeys', next)}
      />
      <FilterSelect
        label="Legal status"
        value={value.legalStatus}
        choices={choices.legalStatus}
        onChange={(next) => update('legalStatus', next)}
      />
    </div>
  )
}

function FilterSelect({
  label,
  value,
  choices,
  onChange,
}: {
  label: string
  value: string
  choices: string[]
  onChange: (value: string) => void
}) {
  return (
    <label>
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">ALL</option>
        {choices.map((choice) => (
          <option value={choice} key={choice}>{choice}</option>
        ))}
      </select>
    </label>
  )
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean))).sort()
}
