import { useMemo, useState } from 'react'

import type { MassPortfolioManifest } from '../../lib/mass-portfolio-types'
import { LanguageNetworkCanvas } from './LanguageNetworkCanvas'
import { adaptMassPortfolio, filterMassPortfolioCards, type MassPortfolioFilters as FilterState } from './mass-portfolio-adapter'
import { MassPortfolioEvidence } from './MassPortfolioEvidence'
import { MassPortfolioFilters } from './MassPortfolioFilters'
import { MassStatusBadge } from './MassStatusBadge'

const EMPTY_FILTERS: FilterState = { program: '', overallStatus: '', gate: '', gateStatus: '' }

export function MassPortfolioView({ manifest, compact = false }: { manifest: MassPortfolioManifest; compact?: boolean }) {
  const portfolio = useMemo(() => adaptMassPortfolio(manifest), [manifest])
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS)
  const [selectedKey, setSelectedKey] = useState(portfolio.cards[0]?.selectionKey ?? '')
  const filtered = useMemo(() => filterMassPortfolioCards(portfolio.cards, filters), [portfolio.cards, filters])
  const lawPassCount = portfolio.cards.filter((card) => card.stages.law.status === 'pass').length
  const finalPassCount = portfolio.cards.filter((card) => card.overallStatus === 'selected' || card.overallStatus === 'legal_pass').length
  const selected = portfolio.cards.find((card) => card.selectionKey === selectedKey) ?? filtered[0] ?? portfolio.cards[0]
  const selectedNode = portfolio.nodes.find((node) => node.attributes.selectionKey === selected?.selectionKey)?.id ?? null
  return (
    <section className="mass-portfolio" aria-label="MASS evaluation portfolio">
      <header><div><span>MASS PORTFOLIO · DETERMINISTIC LEGAL EVALUATION</span><strong>{manifest.run_id}</strong></div><b>{manifest.candidate_count} TOTAL · {filtered.length} VISIBLE · {lawPassCount} LAW PASS · {finalPassCount} FINAL PASS · {manifest.status_counts.failed ?? 0} FAILED</b></header>
      <MassPortfolioFilters cards={portfolio.cards} value={filters} onChange={setFilters} />
      <div className="mass-portfolio__workspace">
        <div className="maas-language-flow__viewport" tabIndex={0} aria-label="MASS evaluation language graph">
          <LanguageNetworkCanvas nodes={portfolio.nodes} edges={portfolio.edges} stageOrder={portfolio.stageOrder} selectedNodeId={selectedNode} onSelectNode={() => undefined} includeDescendants axisLabels={['UNITBOX + MATRIX4 + BOOK', 'DETERMINISTIC HARD GATES', 'ALL CANDIDATE OUTCOMES']} />
        </div>
        {!compact && selected && <MassPortfolioEvidence card={selected} />}
      </div>
      <div className="mass-portfolio__gallery" role="list" aria-label="All evaluated MASS candidates">
        {filtered.map((card, index) => <button type="button" role="listitem" key={card.selectionKey} data-selected={card.selectionKey === selected?.selectionKey} data-status={card.overallStatus} onClick={() => setSelectedKey(card.selectionKey)}>
          <div>{card.previewUrl ? <img src={card.previewUrl} alt={`${card.candidateId} MASS`} /> : <span className="mass-portfolio__placeholder">NO PNG</span>}<i>{String(index + 1).padStart(2, '0')}</i></div>
          <strong>{card.candidateId}</strong><em>{card.program || 'UNASSIGNED'}</em><MassStatusBadge status={card.overallStatus} />
          <small>{(['geometry', 'law', 'capacity', 'parking', 'program', 'vlm', 'selection'] as const).map((stage) => <span key={stage} title={`${stage}: ${card.stages[stage].status}`} data-status={card.stages[stage].status}>{stage.slice(0, 1).toUpperCase()}</span>)}</small>
        </button>)}
      </div>
    </section>
  )
}
