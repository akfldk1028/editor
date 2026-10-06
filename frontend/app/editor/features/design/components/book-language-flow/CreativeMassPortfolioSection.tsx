import type { Dispatch, RefObject, SetStateAction } from 'react';

import type { CreativeMassCard } from '../../lib/language-system-types';
import {
  type CreativeMassFilterState,
  CreativeMassFilters,
} from './CreativeMassFilters';
import type {
  AdaptedCreativePortfolio,
  CreativePortfolioPage,
} from './creative-portfolio-adapter';
import { EvidencePanelBoundary } from './EvidencePanelBoundary';
import { CreativeMassEvidence } from './ExecutedMassEvidence';
import { LanguageNetworkCanvas } from './LanguageNetworkCanvas';

interface CreativeMassPortfolioSectionProps {
  creativeRunId: string | undefined;
  creativePortfolio: AdaptedCreativePortfolio;
  filteredCreativeCards: CreativeMassCard[];
  creativeFilters: CreativeMassFilterState;
  setCreativeFilters: Dispatch<SetStateAction<CreativeMassFilterState>>;
  setCreativePage: Dispatch<SetStateAction<number>>;
  creativePageResult: CreativePortfolioPage;
  selectedCreativeMass: CreativeMassCard | null;
  setSelectedCreativeKey: Dispatch<SetStateAction<string>>;
  selectedNodeId: string | null;
  selectedCreativeNodeId: string | null;
  setSelectedNodeId: Dispatch<SetStateAction<string | null>>;
  handleSelectNode: (nodeId: string) => void;
  viewportRef: RefObject<HTMLDivElement | null>;
  compact: boolean;
}

export function CreativeMassPortfolioSection({
  creativeRunId,
  creativePortfolio,
  filteredCreativeCards,
  creativeFilters,
  setCreativeFilters,
  setCreativePage,
  creativePageResult,
  selectedCreativeMass,
  setSelectedCreativeKey,
  selectedNodeId,
  selectedCreativeNodeId,
  setSelectedNodeId,
  handleSelectNode,
  viewportRef,
  compact,
}: CreativeMassPortfolioSectionProps) {
  return (
    <section className="creative-mass-portfolio" aria-label="Creative MASS choice pool">
      <header>
        <div>
          <span>PRE-LEGAL CREATIVE MASS CHOICE POOL</span>
          <strong>{creativeRunId}</strong>
        </div>
        <b>{creativePortfolio.cards.length} TOTAL · {filteredCreativeCards.length} MATCHING · LEGAL NOT EVALUATED</b>
      </header>
      <CreativeMassFilters
        cards={creativePortfolio.cards}
        value={creativeFilters}
        onChange={(next) => {
          setCreativeFilters(next);
          setCreativePage(1);
        }}
      />
      <div className="creative-mass-portfolio__workspace">
        <div
          className="maas-language-flow__viewport"
          ref={viewportRef}
          tabIndex={0}
          aria-label="Creative MASS portfolio graph"
        >
          <LanguageNetworkCanvas
            nodes={creativePortfolio.nodes}
            edges={creativePortfolio.edges}
            stageOrder={creativePortfolio.stageOrder}
            selectedNodeId={selectedNodeId ?? selectedCreativeNodeId}
            onSelectNode={handleSelectNode}
            includeDescendants
            axisLabels={['PRE-LEGAL PORTFOLIO', 'BASEVOLUME MORPHOLOGY FAMILIES', '100 CHOICE-POOL MASSES']}
          />
        </div>
        {!compact && selectedCreativeMass && (
          <EvidencePanelBoundary resetKey={selectedCreativeMass.selectionKey}>
            <CreativeMassEvidence mass={selectedCreativeMass} />
          </EvidencePanelBoundary>
        )}
      </div>
      <nav className="creative-mass-gallery" aria-label="Creative MASS candidates">
        <header>
          <span>PAGE {creativePageResult.page} / {creativePageResult.pageCount}</span>
          <div>
            <button
              type="button"
              disabled={creativePageResult.page === 1}
              onClick={() => setCreativePage((page) => Math.max(1, page - 1))}
            >PREVIOUS</button>
            <button
              type="button"
              disabled={creativePageResult.page === creativePageResult.pageCount}
              onClick={() => setCreativePage((page) => Math.min(creativePageResult.pageCount, page + 1))}
            >NEXT</button>
          </div>
        </header>
        <div>
          {creativePageResult.items.map((mass, index) => (
            <button
              type="button"
              key={mass.selectionKey}
              data-selected={mass.selectionKey === selectedCreativeMass?.selectionKey}
              onClick={() => {
                setSelectedCreativeKey(mass.selectionKey);
                const node = creativePortfolio.nodes.find(
                  (item) => item.attributes.selectionKey === mass.selectionKey,
                );
                setSelectedNodeId(node?.id ?? null);
              }}
              aria-label={`${mass.candidateId} ${mass.family} pre-legal MASS`}
            >
              <img src={mass.renderUrl} alt={`${mass.candidateId} creative MASS`} />
              <span>{String((creativePageResult.page - 1) * creativePageResult.pageSize + index + 1).padStart(3, '0')}</span>
              <strong>{mass.candidateId}</strong>
              <em>{mass.family} · {mass.capacityBand} · {mass.storeys}F</em>
            </button>
          ))}
        </div>
      </nav>
    </section>
  );
}
