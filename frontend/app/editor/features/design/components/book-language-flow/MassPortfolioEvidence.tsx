import type { MassPortfolioCard, MassStageName } from '../../lib/mass-portfolio-types'
import { MassStatusBadge } from './MassStatusBadge'

const STAGES: MassStageName[] = ['geometry', 'law', 'capacity', 'parking', 'program', 'vlm', 'selection']

export function MassPortfolioEvidence({ card }: { card: MassPortfolioCard }) {
  return (
    <aside className="mass-portfolio-evidence" aria-label="Selected MASS evaluation evidence">
      <header><span>EVALUATION LEDGER</span><h3>{card.candidateId}</h3><MassStatusBadge status={card.overallStatus} /></header>
      <div className="mass-portfolio-evidence__preview">
        {card.previewUrl ? <img src={card.previewUrl} alt={`${card.candidateId} evaluated MASS`} /> : <div role="img" aria-label="Preview not available">NO CANDIDATE-BOUND PNG</div>}
      </div>
      <dl>{STAGES.map((name) => <div key={name}><dt>{name}</dt><dd><MassStatusBadge status={card.stages[name].status} />{card.stages[name].reasons.length > 0 && <small>{card.stages[name].reasons.join(' · ')}</small>}</dd></div>)}</dl>
      <section><span>TERMINAL REASONS</span><p>{card.terminalReasons.length ? card.terminalReasons.join(' · ') : 'NONE'}</p></section>
      <footer><code>{card.geometryHash}</code><code>{card.programHash}</code></footer>
    </aside>
  )
}
