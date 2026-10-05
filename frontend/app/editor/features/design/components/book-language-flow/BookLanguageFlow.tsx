import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Maximize2, Minimize2, RotateCcw } from 'lucide-react';

import {
  getCreativeMassPortfolio,
  getMassPortfolioEvaluations,
  getMaasLanguageSystem,
} from '../../lib/api-client';
import type {
  CreativePortfolioManifest,
  MaasLanguageSystemManifest,
} from '../../lib/language-system-types';
import type { MassPortfolioManifest } from '../../lib/mass-portfolio-types';
import { EvidencePanelBoundary } from './EvidencePanelBoundary';
import { CreativeMassEvidence, ExecutedMassEvidence } from './ExecutedMassEvidence';
import { executionRunCopy } from './execution-mode';
import { useExecutionArchive } from './useExecutionArchive';
import { LanguageNetworkCanvas } from './LanguageNetworkCanvas';
import { executedMassNodeId, massLabel } from './execution-graph-model';
import { useExecutionGraph } from './useExecutionGraph';
import {
  adaptCreativePortfolio,
  creativePortfolioPage,
} from './creative-portfolio-adapter';
import {
  CreativeMassFilters,
  filterCreativeMassCards,
  type CreativeMassFilterState,
} from './CreativeMassFilters';
import { MassPortfolioView } from './MassPortfolioView';
import './book-language-flow.css';

interface BookLanguageFlowProps {
  pnu?: string;
  compact?: boolean;
  standalone?: boolean;
}

type GraphView = 'full' | 'selected' | 'archive' | 'creative';

const EMPTY_CREATIVE_FILTERS: CreativeMassFilterState = {
  family: '',
  capacityBand: '',
  storeys: '',
  legalStatus: '',
};

export function BookLanguageFlow({ compact = false, standalone = false }: BookLanguageFlowProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const { archive, outcomeGraph, selectedMassIndex, setSelectedMassIndex, archiveError, lastSyncAt, executionState, executionError, selectedMass, passportBinding, selectedPassport, selectedPassportError, recentMassCards, vlmReview, selectRun, executeMass } = useExecutionArchive();
  const [languageManifest, setLanguageManifest] = useState<MaasLanguageSystemManifest | null>(null);
  const [creativeManifest, setCreativeManifest] = useState<CreativePortfolioManifest | null>(null);
  const [massPortfolioManifest, setMassPortfolioManifest] = useState<MassPortfolioManifest | null>(null);
  const [creativeError, setCreativeError] = useState('');
  const [creativeFilters, setCreativeFilters] = useState<CreativeMassFilterState>(EMPTY_CREATIVE_FILTERS);
  const [creativePage, setCreativePage] = useState(1);
  const [selectedCreativeKey, setSelectedCreativeKey] = useState('');
  const [graphView, setGraphView] = useState<GraphView>('full');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getMaasLanguageSystem(controller.signal)
      .then(setLanguageManifest)
      .catch(() => setLanguageManifest(null));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getMassPortfolioEvaluations(undefined, controller.signal)
      .then(setMassPortfolioManifest)
      .catch(() => setMassPortfolioManifest(null));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getCreativeMassPortfolio(undefined, controller.signal)
      .then((payload) => {
        setCreativeManifest(payload);
        const first = adaptCreativePortfolio(payload).cards[0];
        setSelectedCreativeKey((current) => current || first?.selectionKey || '');
        setCreativeError('');
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setCreativeError(
            reason instanceof Error ? reason.message : 'Creative MASS portfolio fetch failed',
          );
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const selected = archive?.masses.find((mass) => mass.index === selectedMassIndex);
    setSelectedNodeId(
      graphView === 'full' && selected
        ? executedMassNodeId(selected)
        : graphView === 'selected'
          ? 'result:mass'
          : null,
    );
  }, [archive, graphView, selectedMassIndex]);

  useEffect(() => {
    if (!isFullscreen) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsFullscreen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [isFullscreen]);

  const creativePortfolio = useMemo(
    () => creativeManifest ? adaptCreativePortfolio(creativeManifest) : null,
    [creativeManifest],
  );
  const filteredCreativeCards = useMemo(
    () => creativePortfolio
      ? filterCreativeMassCards(creativePortfolio.cards, creativeFilters)
      : [],
    [creativeFilters, creativePortfolio],
  );
  const creativePageResult = useMemo(
    () => creativePortfolioPage(filteredCreativeCards, creativePage),
    [creativePage, filteredCreativeCards],
  );
  const selectedCreativeMass = useMemo(
    () => creativePortfolio?.cards.find((card) => card.selectionKey === selectedCreativeKey)
      ?? creativePortfolio?.cards[0]
      ?? null,
    [creativePortfolio, selectedCreativeKey],
  );
  const selectedCreativeNodeId = useMemo(() => {
    if (!creativePortfolio || !selectedCreativeMass) return null;
    return creativePortfolio.nodes.find(
      (node) => node.attributes.selectionKey === selectedCreativeMass.selectionKey,
    )?.id ?? null;
  }, [creativePortfolio, selectedCreativeMass]);
  const { displayedNodes, displayedEdges, displayedStageOrder, fullSelectionEdgeIds } = useExecutionGraph({
    languageManifest, archive, selectedPassport, selectedMass, outcomeGraph, graphView, selectedMassIndex, selectedNodeId,
  });
  const vlmStage = selectedPassport?.stages.find((stage) => stage.id === 'vlm');
  const portfolioVlmAudit = archive?.portfolio_vlm_audit;
  const portfolioVlmEvaluated = Boolean(portfolioVlmAudit?.status && portfolioVlmAudit.status !== 'not_requested');
  const vlmStatusLabel = portfolioVlmEvaluated
    ? `PAID ${portfolioVlmAudit?.hard_pass ? 'PASS' : 'FAIL'}`
    : !vlmStage || vlmStage.status === 'not_evaluated' ? 'OFF' : 'ON';
  const retrievedReferenceCount = selectedPassport?.retrieved_references?.length ?? 0;
  const activeVlmReferenceCount = selectedPassport?.activation_graph.nodes.filter(
    (node) => node.kind === 'vlm_reference_image',
  ).length ?? 0;

  const resetView = () => {
    setSelectedNodeId(
      graphView === 'selected'
        ? 'result:mass'
        : graphView === 'creative'
          ? selectedCreativeNodeId
          : null,
    );
    viewportRef.current?.scrollTo({ left: 0, top: 0, behavior: 'smooth' });
  };

  const changeGraphView = (nextView: GraphView) => {
    setGraphView(nextView);
    setSelectedNodeId(
      nextView === 'full' && selectedMass
        ? executedMassNodeId(selectedMass)
        : nextView === 'selected'
          ? 'result:mass'
          : nextView === 'creative'
            ? selectedCreativeNodeId
            : null,
    );
    viewportRef.current?.scrollTo({ left: 0, top: 0 });
  };

  const handleSelectNode = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    if (graphView === 'creative') {
      const node = creativePortfolio?.nodes.find((item) => item.id === nodeId);
      const selectionKey = node?.attributes.selectionKey;
      if (typeof selectionKey === 'string') setSelectedCreativeKey(selectionKey);
      return;
    }
    const mass = archive?.masses.find((item) => executedMassNodeId(item) === nodeId);
    if (mass) setSelectedMassIndex(mass.index);
  };

  const executeSelectedMass = () => executeMass(() => {
    setGraphView('full');
    setSelectedNodeId(null);
  });

  const content = (
    <section
      className={`maas-language-flow${isFullscreen ? ' maas-language-flow--fullscreen' : ''}${standalone ? ' maas-language-flow--standalone' : ''}${compact ? ' maas-language-flow--compact' : ''}`}
      data-testid="maas-book-language-flow"
    >
      <header className="maas-language-flow__header">
        <div>
          <div className="maas-language-flow__kicker">MAAS / SINGLE CAUSAL GEOMETRY GRAPH</div>
          <h1>One MASS · one executable provenance graph</h1>
          <p>BOOK is typed geometry language, never image evidence. Select one generated MASS to trace its actual program, gates, render, VLM evidence and final selection.</p>
        </div>
        <div className="maas-language-flow__header-actions">
          <button type="button" onClick={resetView} aria-label="선택 경로 초기화" title="Reset selected path"><RotateCcw size={15} /></button>
          <button type="button" onClick={() => setIsFullscreen((current) => !current)} aria-label={isFullscreen ? '전체 화면 종료' : '전체 화면'}>
            {isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
        </div>
      </header>

      <div className="maas-language-flow__toolbar maas-language-flow__toolbar--single">
        <div className="maas-language-flow__graph-modes" role="tablist" aria-label="Geometry graph view">
          <button
            type="button"
            role="tab"
            aria-selected={graphView === 'full'}
            data-selected={graphView === 'full'}
            onClick={() => changeGraphView('full')}
          >FULL GRAPH</button>
          <button
            type="button"
            role="tab"
            aria-selected={graphView === 'selected'}
            data-selected={graphView === 'selected'}
            onClick={() => changeGraphView('selected')}
          >SELECTED MASS PATH</button>
          <button
            type="button"
            role="tab"
            aria-selected={graphView === 'archive'}
            data-selected={graphView === 'archive'}
            onClick={() => changeGraphView('archive')}
          >MASS ARCHIVE</button>
          <button
            type="button"
            role="tab"
            aria-selected={graphView === 'creative'}
            data-selected={graphView === 'creative'}
            onClick={() => changeGraphView('creative')}
          >MASS PORTFOLIO</button>
        </div>
        <div
          className="maas-language-flow__single-graph-label"
          title={`Run: ${archive?.selected_run_id ?? 'loading'} · MASS: ${selectedMass?.variant_id ?? 'loading'}`}
        >
          <span>{
            graphView === 'full'
              ? 'FULL BOOK LANGUAGE + EXECUTED MASS RESULTS'
              : graphView === 'selected'
                ? 'SELECTED EXECUTION PASSPORT'
                : graphView === 'archive'
                  ? 'ACTUAL MASS RESULTS ONLY'
                  : massPortfolioManifest
                    ? 'ALL MASS RESULTS + LEGAL EVALUATION LEDGER'
                    : 'PRE-LEGAL CREATIVE CHOICE POOL'
          }</span>
          <strong>{
            graphView === 'creative'
              ? massPortfolioManifest?.run_id ?? selectedCreativeMass?.candidateId ?? 'LOADING'
              : selectedMass?.variant_id ?? (languageManifest ? 'LANGUAGE CATALOG · NO MASS SELECTED' : 'LOADING')
          }</strong>
        </div>
        {archive && graphView !== 'creative' && (
          <div className="maas-language-flow__counts">
            <span><b>{String(archive.mass_count).padStart(2, '0')}</b> EXECUTED</span>
            <span><b>{String(archive.run_count).padStart(2, '0')}</b> RUNS</span>
            <span><b>{archive.run_status.toUpperCase()}</b> PORTFOLIO</span>
            <span><b>0</b> BOOK RASTERS</span>
            <span><b>{vlmStatusLabel}</b> VLM</span>
            <span><b>{retrievedReferenceCount}</b> RETRIEVED / <b>{activeVlmReferenceCount}</b> USED</span>
            <span><b>{archive.editor_provenance ? 'ARCHIVE' : 'LIVE'}</b> SYNC {lastSyncAt || '--:--:--'}</span>
          </div>
        )}
      </div>

      {graphView !== 'creative' && archiveError && (
        <div className="maas-language-flow__state" role="alert">{archiveError}</div>
      )}
      {passportBinding.error && (
        <div className="maas-language-flow__state" role="alert">{passportBinding.error}</div>
      )}
      {archive && graphView !== 'creative' && (
        <nav className="execution-run-timeline" aria-label="MASS 실행 시간순 아카이브">
          <header><span>EXECUTION RUN TIMELINE</span><strong>{archive.editor_provenance ? 'SAVED RUNS · CLICK TO VIEW' : 'NEWEST → OLDEST · CLICK TO REPLAY'}</strong></header>
          <div>
            {[...archive.runs].reverse().map((run, runIndex) => (
              <button
                type="button"
                key={run.run_id}
                data-selected={run.run_id === archive.selected_run_id}
                data-replayable={run.replayable}
                onClick={() => selectRun(run.run_id)}
                title={run.run_id}
              >
                <span>{String(runIndex + 1).padStart(2, '0')}</span>
                <b>{run.run_id.replace('book-program-portfolios-', '')}</b>
                <em>{run.selected_mass_count} MASS · {run.replayable ? executionRunCopy(run.execution_mode) : 'NO FINAL'}</em>
              </button>
            ))}
          </div>
        </nav>
      )}
      {archive && archive.masses.length === 0 && (
        <div className="maas-language-flow__state" role="status">
          이 run은 실행 기록은 보존됐지만 최종 선택 MASS가 없습니다. 실행 상태: {archive.run_status}.
        </div>
      )}
      {graphView !== 'creative' && !archiveError && !archive && (
        <div className="maas-language-flow__state" role="status">실행 MASS 아카이브를 불러오는 중입니다.</div>
      )}

      {graphView === 'creative' && !massPortfolioManifest && creativeError && (
        <div className="maas-language-flow__state" role="alert">{creativeError}</div>
      )}
      {graphView === 'creative' && !massPortfolioManifest && !creativeError && !creativePortfolio && (
        <div className="maas-language-flow__state" role="status">Loading the creative MASS choice pool.</div>
      )}
      {graphView === 'creative' && massPortfolioManifest && (
        <MassPortfolioView manifest={massPortfolioManifest} compact={compact} />
      )}
      {graphView === 'creative' && !massPortfolioManifest && creativePortfolio && (
        <section className="creative-mass-portfolio" aria-label="Creative MASS choice pool">
          <header>
            <div>
              <span>PRE-LEGAL CREATIVE MASS CHOICE POOL</span>
              <strong>{creativeManifest?.run_id}</strong>
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
      )}

      {archive && graphView === 'archive' && (
        <section className="mass-only-archive" aria-label="실제 MASS 결과만 보기">
          <header>
            <div>
              <span>ACTUAL MASS ARCHIVE</span>
              <strong title={archive.selected_run_id}>{archive.selected_run_id}</strong>
            </div>
            <b>{recentMassCards.length} REPLAYABLE MASS RESULTS</b>
          </header>
          <div>
            {recentMassCards.map((mass) => (
              <button
                type="button"
                key={mass.key}
                data-selected={mass.selected}
                onClick={() => {
                  if (mass.runId !== archive.selected_run_id) selectRun(mass.runId);
                  else setSelectedMassIndex(mass.massIndex);
                }}
              >
                <img src={mass.previewUrl} alt={`${mass.label} actual MASS`} />
                <span>{String(mass.massIndex).padStart(2, '0')}</span>
                <strong>{massLabel(mass.label)}</strong>
                <em>{mass.operationLabel}</em>
              </button>
            ))}
          </div>
        </section>
      )}

      {graphView !== 'archive' && graphView !== 'creative' && (selectedMass || (graphView === 'full' && languageManifest)) && (
        <div className="maas-language-flow__workspace maas-language-flow__workspace--geometry">
          <div className="maas-language-flow__viewport" ref={viewportRef} tabIndex={0} aria-label="선택한 MASS의 단일 인과 실행 그래프">
            {languageManifest && (graphView === 'full' || selectedPassport) ? (
              <LanguageNetworkCanvas
                nodes={displayedNodes}
                edges={displayedEdges}
                stageOrder={displayedStageOrder}
                selectedNodeId={selectedNodeId}
                onSelectNode={handleSelectNode}
                selectionEdgeIds={fullSelectionEdgeIds}
                axisLabels={['GEOMETRY LANGUAGE', 'MEASURED HARD GATES', 'VISUAL EVIDENCE · FINAL MASS']}
              />
            ) : <div className="maas-language-flow__state">{selectedPassportError || '선택한 MASS 실행 경로를 재생하는 중입니다.'}</div>}
          </div>

          {!compact && archive && selectedMass && (
            <EvidencePanelBoundary resetKey={`${archive.selected_run_id}:${selectedMass.index}`}>
              <ExecutedMassEvidence
                archive={archive}
                mass={selectedMass}
                passport={selectedPassport}
                passportError={selectedPassportError}
                onExecute={executeSelectedMass}
                executionState={executionState}
                executionError={executionError}
                onVlmReview={vlmReview.review}
                vlmReviewState={vlmReview.state}
                vlmReviewError={vlmReview.error}
              />
            </EvidencePanelBoundary>
          )}

          {!compact && archive && selectedMass && (
            <nav className="geometry-result-gallery" aria-label="실제로 실행된 MASS 결과 선택">
              <header><span>ACTUAL EXECUTED MASS RESULTS</span><strong>{recentMassCards.length} ARCHIVED · SELECT ONE TO TRACE</strong></header>
              <div>
                {recentMassCards.map((mass, cardIndex) => (
                  <button
                    type="button"
                    key={mass.key}
                    data-selected={mass.selected}
                    onClick={() => {
                      if (mass.runId !== archive.selected_run_id) {
                        selectRun(mass.runId);
                      } else {
                        setSelectedMassIndex(mass.massIndex);
                        setSelectedNodeId(
                          graphView === 'full' && selectedMass
                            ? executedMassNodeId(selectedMass)
                            : 'result:mass',
                        );
                      }
                    }}
                    aria-label={`${mass.executionId} ${mass.label} MASS 실행 경로 보기`}
                  >
                    <img src={mass.previewUrl} alt={`${mass.label} 실제 실행 MASS`} />
                    <span>{String(cardIndex + 1).padStart(2, '0')}</span>
                    <b>{massLabel(mass.label)}</b>
                  </button>
                ))}
              </div>
            </nav>
          )}
        </div>
      )}

      <footer className="maas-language-flow__footer">
        <span>ONE GRAPH · SELECTED MASS PATH ONLY · BOOK LANGUAGE → GEOMETRY → GATES → RENDER → VLM → SELECTOR</span>
        <strong>{portfolioVlmEvaluated
          ? `PORTFOLIO VLM ${portfolioVlmAudit?.status?.toUpperCase()} · ${portfolioVlmAudit?.model || 'MODEL RECORDED'}`
          : !vlmStage || vlmStage.status === 'not_evaluated'
            ? 'VLM NOT EVALUATED · NO CLAIM'
            : `VLM ${vlmStage.status.toUpperCase()}`}</strong>
      </footer>
    </section>
  );

  return isFullscreen ? createPortal(content, document.body) : content;
}
