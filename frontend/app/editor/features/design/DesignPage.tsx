import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ConstraintSummary from './components/ConstraintSummary';
import ControlPanel from './components/ControlPanel';
import DatumInfoCard from './components/DatumInfoCard';
import DefaultAgentFlowPanel from './components/DefaultAgentFlowPanel';
import { DesignCollaborationPanel } from './components/DesignCollaborationPanel';
import { DesignMassTab } from './components/DesignMassTab';
import { DesignPageHeader, DesignViewTabBar, ParetoEmptyState, ParetoVisibilityToggle } from './components/DesignPageSections';
import FloorPlanViewer from './components/FloorPlanViewer';
import GenerationProgress from './components/GenerationProgress';
import InteractiveDesignPanel from './components/InteractiveDesignPanel';
import LegalBasisPanel from './components/LegalBasisPanel';
import ParetoChart from './components/ParetoChart';
import SiteMapPanel from './components/SiteMapPanel';
import { SunlightSectionDiagram } from './components/SunlightSectionDiagram';
import { useDesignAesthetic } from './hooks/use-design-aesthetic';
import { useDesignFloorPlan } from './hooks/use-design-floor-plan';
import { useDesignJob } from './hooks/use-design-job';
import { useOptimizationStream } from './hooks/use-optimization-stream';
import { cancelJob } from './lib/api-client';
import { ALGORITHMS, BUILDING_TYPES, OBJECTIVE_LABELS } from './lib/design-page-options';
import { featureFitsSite, matchesDesignFeature, normalizeSitePolygon, pickDiverseParetoDesigns, type SiteGeometry } from './lib/design-selection';
import { requiredValue } from './lib/required-value';
import type { DesignData, GeoJSONFeature } from './lib/types';

const DesignPage: React.FC = () => {
  const jobState = useDesignJob();
  const stream = useOptimizationStream();
  const [selectedDesign, setSelectedDesign] = useState<DesignData | null>(null);
  const [activePnu, setActivePnu] = useState('');
  const [buildingType, setBuildingType] = useState('공동주택');
  const [algorithm, setAlgorithm] = useState('maas_legal_envelope');
  const [viewTab, setViewTab] = useState<'mass' | 'floor'>('mass');
  const [actionError, setActionError] = useState<string | null>(null);
  const [interactivePreview, setInteractivePreview] = useState<GeoJSONFeature | null>(null);
  const { aestheticOverlay, setAestheticOverlay, aestheticFacadeStyle, setAestheticFacadeStyle, handleAestheticGenerated } = useDesignAesthetic();
  const [showAllPareto, setShowAllPareto] = useState(false);
  const buildingTypeRequestRef = useRef(buildingType);

  const handlePnuSearch = useCallback(async (pnu: string) => {
    resetPendingFloorPlan();
    setActionError(null);
    setSelectedDesign(null);
    setInteractivePreview(null);
    setFloorPlanResult(null);
    stream.reset();
    setActivePnu(pnu);
    const boundary = await jobState.loadSiteBoundary(pnu);
    if (!boundary) return;
    const resolvedPnu = boundary?.pnu || pnu;
    setActivePnu(resolvedPnu);
    console.log('[Design] boundary:', boundary ? `geometry=${boundary.geometry?.type}, area=${boundary.area_m2}` : 'null');
    // MultiPolygon -> largest Polygon 변환. backend compute_setback_lines가 Polygon만
    // 처리하므로 분할 필지는 대표 대지 조각을 명시적으로 선택한다.
    const site_polygon = normalizeSitePolygon(boundary?.geometry as SiteGeometry | undefined);
    await jobState.loadConstraints({
      pnu: resolvedPnu,
      site_polygon,
      building_type: buildingTypeRequestRef.current,
      include_law_articles: false,
    });
  }, [jobState, buildingType, stream]);

  const handleBuildingTypeChange = useCallback(async (nextType: string) => {
    setBuildingType(nextType);
    if (buildingTypeRequestRef.current === nextType) return;
    buildingTypeRequestRef.current = nextType;
    if (!activePnu || !jobState.sitePolygon) return;
    const site_polygon = normalizeSitePolygon(jobState.sitePolygon as SiteGeometry);
    await jobState.loadConstraints({
      pnu: activePnu,
      site_polygon,
      building_type: nextType,
      include_law_articles: false,
    });
  }, [activePnu, jobState]);

  // Stable ref to avoid SiteMapPanel re-renders (prevents camera reset)
  const handlePnuSearchRef = useRef(handlePnuSearch);
  handlePnuSearchRef.current = handlePnuSearch;

  const handleParcelClick = useCallback((pnu: string, _address: string) => {
    handlePnuSearchRef.current(pnu);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const queryPnu = params.get('pnu') || params.get('address');
    if (!queryPnu) return;
    handlePnuSearchRef.current(queryPnu);
  }, []);

  const handleStart = useCallback(async (options: { maxGenerations: number; populationSize: number }) => {
    setSelectedDesign(null);
    setInteractivePreview(null);
    setFloorPlanResult(null);
    setViewTab('mass');
    setShowAllPareto(false);
    resetPendingFloorPlan();
    // Decompose population into islands (5 islands default)
    const numIslands = 5;
    const popPerIsland = Math.max(3, Math.round(options.populationSize / numIslands));
    const job = await jobState.startJob({
      pnu: activePnu,
      job_spec: {
        options: {
          'Number of generations': options.maxGenerations,
          'num_islands': numIslands,
          'pop_per_island': popPerIsland,
          'building_type': buildingType,
          'algorithm': algorithm,
        },
      },
    });
    if (job) {
      stream.connect(job.id);
    }
  }, [jobState, stream, buildingType, algorithm]);

  const handleCancel = useCallback(async () => {
    if (jobState.job) {
      try {
        await cancelJob(jobState.job.id);
        await stream.refresh(jobState.job.id);
      } catch (error) {
        setActionError(error instanceof Error ? error.message : '설계 실행 취소 실패');
      }
    }
  }, [jobState.job, stream]);

  const findFeatureForDesign = useCallback((design: DesignData): GeoJSONFeature | null => {
    if (!stream.paretoGeojson?.length) return null;
    return stream.paretoGeojson.find(f => matchesDesignFeature(f, design)) || null;
  }, [stream.paretoGeojson]);

  const { floorPlanResult, setFloorPlanResult, floorPlanLoading, floorPlanIndex, setFloorPlanIndex, autoFloorPlan, setAutoFloorPlan, floorAlgorithm, setFloorAlgorithm, runFloorPlan, scheduleAutoFloorPlan, resetPendingFloorPlan } = useDesignFloorPlan({
    paretoGeojson: stream.paretoGeojson, findFeatureForDesign, buildingType, setViewTab, setActionError,
  });

  const handleDesignSelect = useCallback((d: DesignData) => {
    setSelectedDesign(d);
    setInteractivePreview(null);
    setAestheticOverlay(null);
    setAestheticFacadeStyle(null);
    setViewTab('mass');
    scheduleAutoFloorPlan(d);
  }, [scheduleAutoFloorPlan]);

  const handleGenerateFloorPlan = useCallback(async () => {
    if (!selectedDesign) return;
    runFloorPlan(selectedDesign, false);
  }, [selectedDesign, runFloorPlan]);

  // Derive Pareto axis labels from SSE objectives (per building type)
  const xLabel = stream.objectives[0]
    ? (OBJECTIVE_LABELS[stream.objectives[0].name] || stream.objectives[0].name)
    : 'Floor Area (m\u00B2)';
  const yLabel = stream.objectives[1]
    ? (OBJECTIVE_LABELS[stream.objectives[1].name] || stream.objectives[1].name)
    : 'Daylight Score';

  // Compute mass features for 3D map rendering
  const massFeatures = useMemo(() => {
    if (interactivePreview && featureFitsSite(interactivePreview, jobState.sitePolygon)) return [interactivePreview];
    // If user selected a specific design, show only that one
    if (selectedDesign && stream.paretoGeojson?.length) {
      const found = stream.paretoGeojson.find(
        f => matchesDesignFeature(f, selectedDesign),
      );
      if (found && featureFitsSite(found, jobState.sitePolygon)) return [found];
      return [];
    }
    // During optimization, show best design
    if (stream.bestGeojson && featureFitsSite(stream.bestGeojson, jobState.sitePolygon)) return [stream.bestGeojson];
    return [];
  }, [interactivePreview, selectedDesign, stream.paretoGeojson, stream.bestGeojson, jobState.sitePolygon]);

  const selectedMassGeojson = useMemo(() => {
    if (!selectedDesign || !stream.paretoGeojson?.length) return null;
    const found = stream.paretoGeojson.find(
      f => matchesDesignFeature(f, selectedDesign),
    ) || null;
    return featureFitsSite(found, jobState.sitePolygon) ? found : null;
  }, [selectedDesign, stream.paretoGeojson, jobState.sitePolygon]);
  const activeMassGeojson = interactivePreview || selectedMassGeojson || (!selectedDesign ? massFeatures[0] : null) || null;
  const activeMassDesignId = activeMassGeojson?.properties?.design_id ?? selectedDesign?.id ?? undefined;
  const agentFlowStatus = stream.status === 'running' || stream.status === 'connecting'
    ? 'active'
    : stream.status === 'complete'
      ? 'complete'
      : stream.status === 'error'
        ? 'error'
        : stream.status === 'cancelled'
          ? 'stopped'
          : 'idle';

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const debugFeatures = activeMassGeojson ? [activeMassGeojson] : massFeatures;
    (window as unknown as {
      __arrDesignLastMassFeatures?: GeoJSONFeature[];
      __arrDesignActiveMassFeature?: GeoJSONFeature | null;
    }).__arrDesignLastMassFeatures = debugFeatures;
    (window as unknown as {
      __arrDesignActiveMassFeature?: GeoJSONFeature | null;
    }).__arrDesignActiveMassFeature = activeMassGeojson;
  }, [activeMassGeojson, massFeatures]);

  const activePanelDesign = useMemo<DesignData | null>(() => {
    if (selectedDesign) return selectedDesign;
    if (!activeMassGeojson) return null;
    const props = (activeMassGeojson.properties || {}) as Record<string, unknown>;
    const designId = typeof props.design_id === 'number' ? props.design_id : 0;
    return {
      id: designId,
      uid: typeof props.design_uid === 'string' ? props.design_uid : undefined,
      generation: 0,
      parents: [null, null],
      feasible: props.legal_status !== 'fail',
      inputs: [],
      objectives: [
        typeof props.floor_area === 'number' ? props.floor_area : 0,
        typeof props.open_pct === 'number' ? props.open_pct : 0,
      ],
      penalty: 0,
      rank: 1,
      elite: 0,
      algorithm: typeof props.algorithm === 'string' ? props.algorithm : algorithm,
    };
  }, [activeMassGeojson, algorithm, selectedDesign]);

  const visibleParetoDesigns = useMemo(() => {
    if (showAllPareto) {
      const locationChecked = stream.paretoGeojson.length > 0
        ? stream.paretoFront.filter(d => {
          const feat = stream.paretoGeojson.find(f => matchesDesignFeature(f, d));
          return !feat || featureFitsSite(feat, jobState.sitePolygon);
        })
        : stream.paretoFront;
      return locationChecked.length > 0 ? locationChecked : stream.paretoFront;
    }
    return pickDiverseParetoDesigns(stream.paretoFront, stream.paretoGeojson, jobState.sitePolygon, 18);
  }, [showAllPareto, stream.paretoFront, stream.paretoGeojson, jobState.sitePolygon]);

  useEffect(() => {
    if (selectedDesign || stream.status !== 'complete' || visibleParetoDesigns.length === 0) return;
    setSelectedDesign(requiredValue(visibleParetoDesigns[0]));
    setInteractivePreview(null);
    setAestheticOverlay(null);
    setAestheticFacadeStyle(null);
  }, [selectedDesign, stream.status, visibleParetoDesigns]);

  return (
    <div style={{
      width: '100vw',
      height: 'calc(100vh - 56px)',
      display: 'flex',
      background: '#0a0f1a',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    }}>
      {/* Left: Search, legal review, Pareto and candidates */}
      <div style={{
        width: 410,
        padding: '12px 8px',
        overflowY: 'auto' as const,
        display: 'flex',
        flexDirection: 'column' as const,
        gap: 8,
        borderRight: '1px solid #1e293b',
        background: '#0f172a',
        flexShrink: 0,
      }}>
        <DesignPageHeader />

        <ControlPanel
          constraints={jobState.constraints}
          siteArea={jobState.siteArea}
          zones={jobState.zones}
          loading={jobState.loading}
          onPnuSearch={handlePnuSearch}
          onStart={handleStart}
          onCancel={handleCancel}
          status={stream.status}
          pnuValue={activePnu}
          buildingTypes={BUILDING_TYPES}
          buildingType={buildingType}
          onBuildingTypeChange={handleBuildingTypeChange}
          algorithms={ALGORITHMS}
          algorithm={algorithm}
          onAlgorithmChange={setAlgorithm}
        />

        <LegalBasisPanel setbackGeometries={jobState.setbackGeometries} />

        <ConstraintSummary constraints={jobState.constraints} lawArticles={jobState.lawArticles} />

        {/* 지반 레벨 (§119 datum) — envelope 우선, 없으면 datum_result fallback */}
        <DatumInfoCard
          envelope={jobState.setbackGeometries?.sunlight_envelope ?? null}
          datumResult={jobState.setbackGeometries?.datum_result ?? null}
        />

        {/* 정북일조 사선제한 단면도 — 법규 §86① 그대로 2D 시각화 (지도 좌표 독립) */}
        {jobState.zones && jobState.zones.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <SunlightSectionDiagram
              applies={jobState.zones.some((z: string) =>
                z.includes('전용주거') || z.includes('일반주거')
              )}
              targetHeightM={18}
              width={440}
              height={280}
            />
          </div>
        )}

        {stream.status !== 'idle' && (
          <GenerationProgress
            status={stream.status}
            generation={stream.generation}
            maxGenerations={stream.maxGenerations}
            progress={stream.progress}
            feasibleCount={stream.feasibleCount}
            paretoCount={stream.paretoFront.length}
            totalEvaluated={stream.totalDesigns}
            error={stream.error}
          />
        )}

        <div style={{ flexShrink: 0 }}>
          {(stream.paretoFront.length > 0 || stream.scatterHistory.length > 0) ? (
            <ParetoChart
              designs={visibleParetoDesigns}
              scatterHistory={showAllPareto ? stream.scatterHistory : []}
              maxGeneration={stream.maxGenerations}
              selectedId={selectedDesign?.id ?? null}
              onSelect={handleDesignSelect}
              xLabel={xLabel}
              yLabel={yLabel}
            />
          ) : stream.status === 'idle' ? (
            <ParetoEmptyState />
          ) : null}
        </div>

        {/* Tab bar: 매스 | 평면 + 자동 토글 */}
        <DesignViewTabBar
          viewTab={viewTab}
          setViewTab={setViewTab}
          floorAlgorithm={floorAlgorithm}
          setFloorAlgorithm={setFloorAlgorithm}
          autoFloorPlan={autoFloorPlan}
          setAutoFloorPlan={setAutoFloorPlan}
        />

        {stream.paretoFront.length > 18 && (
          <ParetoVisibilityToggle
            showAllPareto={showAllPareto}
            setShowAllPareto={setShowAllPareto}
            paretoFrontCount={stream.paretoFront.length}
            visibleParetoCount={visibleParetoDesigns.length}
          />
        )}

        {/* Tab content */}
        <div style={{ minHeight: 360, overflow: 'visible', display: 'flex', flexDirection: 'column' }}>
          {viewTab === 'mass' ? (
            <DesignMassTab
              designs={visibleParetoDesigns}
              selectedDesign={selectedDesign}
              onSelect={handleDesignSelect}
              objectives={stream.objectives}
              featureForDesign={findFeatureForDesign}
              selectedMassGeojson={selectedMassGeojson}
              showFloorPlanButton={stream.paretoGeojson?.length > 0}
              floorPlanLoading={floorPlanLoading}
              onGenerateFloorPlan={handleGenerateFloorPlan}
            />
          ) : (
            <FloorPlanViewer
              result={floorPlanResult}
              selectedIndex={floorPlanIndex}
              onSelectIndex={setFloorPlanIndex}
              loading={floorPlanLoading}
            />
          )}
        </div>

        {(jobState.error || actionError) && (
          <div role="alert" style={{
            padding: '10px 14px', margin: '0 12px 12px',
            background: 'rgba(69,10,10,0.6)',
            borderRadius: 8,
            border: '1px solid rgba(239,68,68,0.2)',
            color: '#fca5a5',
            fontSize: 13,
            flexShrink: 0,
          }}>
            {jobState.error || actionError}
          </div>
        )}
      </div>

      {/* Center: Map */}
      <div style={{
        flex: 1,
        padding: 12,
        minWidth: 0,
      }}>
          <SiteMapPanel
            sitePolygon={jobState.sitePolygon}
            massFeatures={massFeatures.length > 0 ? massFeatures : undefined}
            selectedDesignId={activeMassDesignId}
            aestheticOverlayUrl={aestheticOverlay?.url ?? null}
            aestheticOverlayStatus={aestheticOverlay?.status ?? null}
            aestheticFacadeStyle={aestheticOverlay?.status.includes('mesh skipped') ? null : aestheticFacadeStyle}
            aestheticFacadeTextureUrl={aestheticOverlay?.textureUrl ?? null}
            aestheticFacadeTexturePanelUrls={aestheticOverlay?.texturePanelUrls ?? null}
            aestheticTexturedGltfUrl={aestheticOverlay?.texturedGltfUrl ?? null}
            aestheticPreviewMode={Boolean(aestheticOverlay?.textureUrl)}
            onParcelClick={handleParcelClick}
            setbackGeometries={jobState.setbackGeometries}
          />
      </div>

      {/* Right: AI collaboration */}
      <DesignCollaborationPanel>
        {activePanelDesign ? (
          <InteractiveDesignPanel
            jobId={jobState.job?.id ?? null}
            design={activePanelDesign}
            massGeojson={activeMassGeojson}
            constraints={jobState.constraints}
            sitePolygon={jobState.sitePolygon}
            siteArea={jobState.siteArea}
            pnu={activePnu}
            buildingType={buildingType}
            algorithm={algorithm}
            sunlightEnvelope={jobState.setbackGeometries?.sunlight_envelope ?? null}
            setbackGeometries={jobState.setbackGeometries}
            onPreviewCandidate={setInteractivePreview}
            onAestheticGenerated={handleAestheticGenerated}
          />
        ) : (
          <DefaultAgentFlowPanel pnu={activePnu} status={agentFlowStatus} />
        )}
      </DesignCollaborationPanel>
    </div>
  );
};

export default DesignPage;
