import { DesignCollaborationPanel } from './components/DesignCollaborationPanel';
import { useDesignAesthetic } from './hooks/use-design-aesthetic';
import { useDesignFloorPlan } from './hooks/use-design-floor-plan';
import { featureFitsSite, pickDiverseParetoDesigns, normalizeSitePolygon, matchesDesignFeature, type SiteGeometry } from './lib/design-selection';
import { requiredValue } from './lib/required-value';
import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import type { DesignData, GeoJSONFeature } from './lib/types';
import { cancelJob } from './lib/api-client';
import { useDesignJob } from './hooks/use-design-job';
import { useOptimizationStream } from './hooks/use-optimization-stream';
import ControlPanel from './components/ControlPanel';
import ConstraintSummary from './components/ConstraintSummary';
import DatumInfoCard from './components/DatumInfoCard';
import { MassExecutionPassportCard } from './components/MassExecutionPassportCard';
import LegalBasisPanel from './components/LegalBasisPanel';
import { SunlightSectionDiagram } from './components/SunlightSectionDiagram';
import GenerationProgress from './components/GenerationProgress';
import ParetoChart from './components/ParetoChart';
import DesignInspector from './components/DesignInspector';
import DesignList from './components/DesignList';
import SiteMapPanel from './components/SiteMapPanel';
import FloorPlanViewer from './components/FloorPlanViewer';
import InteractiveDesignPanel from './components/InteractiveDesignPanel';
import DefaultAgentFlowPanel from './components/DefaultAgentFlowPanel';

const OBJECTIVE_LABELS: Record<string, string> = {
  floor_area: 'Floor Area (m\u00B2)',
  daylight_score: 'Daylight Score',
  landscaping_pct: 'Open Space (%)',
  setback: 'Setback (m)',
  bcr: 'BCR (%)',
  far: 'FAR (%)',
  height: 'Height (m)',
};

const BUILDING_TYPES = [
  { key: '공동주택', label: '공동주택 (아파트)', floorHeight: 2.8 },
  { key: '근린생활시설', label: '근린생활시설', floorHeight: 3.5 },
  { key: '업무시설', label: '업무시설 (오피스)', floorHeight: 3.8 },
  { key: '판매시설', label: '판매시설 (상가)', floorHeight: 4.0 },
  { key: '숙박시설', label: '숙박시설 (호텔)', floorHeight: 3.0 },
  { key: '문화집회시설', label: '문화 및 집회시설', floorHeight: 4.5 },
  { key: '의료시설', label: '의료시설', floorHeight: 3.6 },
  { key: '교육연구시설', label: '교육연구시설', floorHeight: 3.5 },
  { key: '공장', label: '공장', floorHeight: 5.0 },
  { key: '창고시설', label: '창고시설', floorHeight: 6.0 },
];

const ALGORITHMS = [
  { key: 'maas_legal_envelope', label: 'MAAS 법규 탐색' },
  { key: 'all', label: 'Legacy 10종 비교' },
];

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
        <div style={{
          padding: '4px 8px 14px',
        }}>
          <h2 style={{
            color: '#e2e8f0',
            fontSize: 17,
            fontWeight: 700,
            margin: 0,
            letterSpacing: '-0.01em',
          }}>
            건물 매스 최적화
          </h2>
          <p style={{ color: '#475569', fontSize: 11, margin: '4px 0 0', letterSpacing: '0.02em' }}>
            MAAS Legal Morphology Search
          </p>
        </div>

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
            <div style={{
              background: 'rgba(30,41,59,0.5)',
              borderRadius: 10,
              padding: 32,
              textAlign: 'center' as const,
              color: '#334155',
              border: '1px dashed #1e293b',
            }}>
              <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>&#x25B3;</div>
              <div style={{ fontSize: 13, lineHeight: 1.6 }}>
                왼쪽 지도에서 대지를 선택하고<br />
                최적화를 시작하면<br />
                파레토 프론트가 표시됩니다
              </div>
            </div>
          ) : null}
        </div>

        {/* Tab bar: 매스 | 평면 + 자동 토글 */}
        <div style={{
          display: 'flex', alignItems: 'center', padding: '6px 12px 0',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
          flexShrink: 0,
        }}>
          {(['mass', 'floor'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setViewTab(tab)}
              style={{
                flex: 1, padding: '7px 0', border: 'none', cursor: 'pointer',
                fontSize: 11, fontWeight: 600, letterSpacing: '0.05em',
                background: 'transparent',
                color: viewTab === tab ? '#e2e8f0' : '#475569',
                borderBottom: viewTab === tab ? '2px solid #60c8ff' : '2px solid transparent',
                transition: 'all 0.15s',
              }}
            >
              {tab === 'mass' ? '매스' : '평면'}
            </button>
          ))}
          <select
            value={floorAlgorithm}
            onChange={e => setFloorAlgorithm(e.target.value)}
            style={{
              marginLeft: 6, padding: '2px 4px', borderRadius: 4,
              border: '1px solid #334155', background: '#0f172a',
              color: '#94a3b8', fontSize: 9, cursor: 'pointer',
              flexShrink: 0,
            }}
          >
            <option value="ga">GA</option>
            <option value="subdivision">분할</option>
            <option value="mcts">MCTS</option>
            <option value="packing">패킹</option>
            <option value="graph2plan">Graph2Plan</option>
          </select>
          <button
            onClick={() => setAutoFloorPlan(prev => !prev)}
            title={autoFloorPlan ? '자동 평면 생성 켜짐' : '자동 평면 생성 꺼짐'}
            style={{
              marginLeft: 4, padding: '3px 8px', borderRadius: 6,
              border: 'none', cursor: 'pointer', fontSize: 9, fontWeight: 600,
              background: autoFloorPlan ? 'rgba(96,200,255,0.12)' : 'rgba(255,255,255,0.03)',
              color: autoFloorPlan ? '#60c8ff' : '#475569',
              transition: 'all 0.15s', whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            자동 {autoFloorPlan ? 'ON' : 'OFF'}
          </button>
        </div>

        {stream.paretoFront.length > 18 && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '7px 12px 0',
            color: '#64748b',
            fontSize: 10,
            flexShrink: 0,
          }}>
            <span>
              {showAllPareto ? `전체 ${stream.paretoFront.length}개 표시` : `최적 후보 ${visibleParetoDesigns.length}개 우선 표시`}
            </span>
            <button
              onClick={() => setShowAllPareto(prev => !prev)}
              style={{
                border: '1px solid rgba(96,200,255,0.22)',
                background: showAllPareto ? 'rgba(96,200,255,0.08)' : 'rgba(16,185,129,0.12)',
                color: showAllPareto ? '#60c8ff' : '#34d399',
                borderRadius: 6,
                padding: '3px 7px',
                fontSize: 10,
                cursor: 'pointer',
              }}
            >
              {showAllPareto ? '최적만' : '전체보기'}
            </button>
          </div>
        )}

        {/* Tab content */}
        <div style={{ minHeight: 360, overflow: 'visible', display: 'flex', flexDirection: 'column' }}>
          {viewTab === 'mass' ? (
            <div style={{ padding: '8px 12px', minHeight: 0 }}>
              <DesignList
                designs={visibleParetoDesigns}
                selectedId={selectedDesign?.id ?? null}
                selectedUid={selectedDesign?.uid ?? null}
                selectedAlgorithm={selectedDesign?.algorithm ?? null}
                onSelect={handleDesignSelect}
                objectiveNames={stream.objectives.map(o => o.name)}
                featureForDesign={findFeatureForDesign}
              />

              {selectedDesign && (
                <div style={{ marginTop: 8 }}>
                  <DesignInspector
                    design={selectedDesign}
                    objectiveNames={stream.objectives.map(o => o.name)}
                    feature={selectedMassGeojson}
                  />
                  <MassExecutionPassportCard
                    value={selectedMassGeojson?.properties?.mass_execution_passport}
                    title={String(
                      selectedMassGeojson?.properties?.variant_id
                      || selectedMassGeojson?.properties?.mass_shape
                      || `MASS ${selectedDesign.id}`
                    )}
                  />
                  {/* 평면 생성 버튼 */}
                  {stream.paretoGeojson?.length > 0 && (
                    <button
                      onClick={handleGenerateFloorPlan}
                      disabled={floorPlanLoading}
                      style={{
                        width: '100%', marginTop: 10, padding: '10px 0',
                        borderRadius: 8, border: 'none', cursor: 'pointer',
                        fontSize: 12, fontWeight: 700, letterSpacing: '0.03em',
                        background: floorPlanLoading
                          ? 'rgba(96,200,255,0.08)'
                          : 'linear-gradient(135deg, rgba(96,200,255,0.15), rgba(96,200,255,0.08))',
                        color: '#60c8ff',
                        transition: 'all 0.15s',
                      }}
                    >
                      {floorPlanLoading ? '생성 중...' : '⊞ 평면 생성'}
                    </button>
                  )}
                </div>
              )}
            </div>
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
