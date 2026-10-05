import { requiredValue } from './lib/required-value';
import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import type { DesignData, FloorPlanResult, GeoJSONFeature, MaasAestheticResult } from './lib/types';
import { cancelJob, generateFloorPlan } from './lib/api-client';
import { getRoomPreset } from './lib/room-presets';
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

type SiteGeometry = { type: string; coordinates: unknown };

function outerRing(geometry: SiteGeometry | GeoJSONFeature['geometry'] | null | undefined): number[][] | null {
  if (!geometry) return null;
  if (geometry.type === 'Polygon') return (geometry.coordinates as number[][][])[0] || null;
  if (geometry.type === 'MultiPolygon') return largestPolygonCoordinates(geometry.coordinates as unknown as number[][][][])?.[0] || null;
  return null;
}

function ringArea(ring: number[][] | null | undefined): number {
  if (!ring || ring.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = requiredValue(ring[i]);
    const b = requiredValue(ring[(i + 1) % ring.length]);
    sum += requiredValue(a[0]) * requiredValue(b[1]) - requiredValue(b[0]) * requiredValue(a[1]);
  }
  return Math.abs(sum) / 2;
}

function largestPolygonCoordinates(polygons: number[][][][] | null | undefined): number[][][] | null {
  if (!Array.isArray(polygons) || polygons.length === 0) return null;
  return polygons.reduce<number[][][] | null>((best, polygon) => {
    if (!Array.isArray(polygon) || !polygon[0]) return best;
    if (!best) return polygon;
    return ringArea(polygon[0]) > ringArea(best[0]) ? polygon : best;
  }, null);
}

function pointInRing(point: [number, number], ring: number[][]): boolean {
  const [x, y] = point;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = requiredValue(requiredValue(ring[i])[0]), yi = requiredValue(requiredValue(ring[i])[1]);
    const xj = requiredValue(requiredValue(ring[j])[0]), yj = requiredValue(requiredValue(ring[j])[1]);
    const intersect = ((yi > y) !== (yj > y))
      && (x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-12) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function orientation(a: number[], b: number[], c: number[]): number {
  const value = (requiredValue(b[1]) - requiredValue(a[1])) * (requiredValue(c[0]) - requiredValue(b[0])) - (requiredValue(b[0]) - requiredValue(a[0])) * (requiredValue(c[1]) - requiredValue(b[1]));
  if (Math.abs(value) < 1e-12) return 0;
  return value > 0 ? 1 : 2;
}

function onSegment(a: number[], b: number[], c: number[]): boolean {
  return requiredValue(b[0]) <= Math.max(requiredValue(a[0]), requiredValue(c[0])) + 1e-12
    && requiredValue(b[0]) + 1e-12 >= Math.min(requiredValue(a[0]), requiredValue(c[0]))
    && requiredValue(b[1]) <= Math.max(requiredValue(a[1]), requiredValue(c[1])) + 1e-12
    && requiredValue(b[1]) + 1e-12 >= Math.min(requiredValue(a[1]), requiredValue(c[1]));
}

function segmentsIntersect(a1: number[], a2: number[], b1: number[], b2: number[]): boolean {
  const o1 = orientation(a1, a2, b1);
  const o2 = orientation(a1, a2, b2);
  const o3 = orientation(b1, b2, a1);
  const o4 = orientation(b1, b2, a2);
  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSegment(a1, b1, a2)) return true;
  if (o2 === 0 && onSegment(a1, b2, a2)) return true;
  if (o3 === 0 && onSegment(b1, a1, b2)) return true;
  if (o4 === 0 && onSegment(b1, a2, b2)) return true;
  return false;
}

function closeRing(ring: number[][]): number[][] {
  if (ring.length < 2) return ring;
  const first = requiredValue(ring[0]);
  const last = requiredValue(ring[ring.length - 1]);
  return requiredValue(first[0]) === requiredValue(last[0]) && requiredValue(first[1]) === requiredValue(last[1]) ? ring : [...ring, first];
}

function ringsOverlap(siteRing: number[][], featureRing: number[][]): boolean {
  if (siteRing.length < 3 || featureRing.length < 3) return true;
  if (featureRing.some(p => pointInRing([requiredValue(p[0]), requiredValue(p[1])], siteRing))) return true;
  if (siteRing.some(p => pointInRing([requiredValue(p[0]), requiredValue(p[1])], featureRing))) return true;
  const site = closeRing(siteRing);
  const feature = closeRing(featureRing);
  for (let i = 0; i < site.length - 1; i++) {
    for (let j = 0; j < feature.length - 1; j++) {
      if (segmentsIntersect(requiredValue(site[i]), requiredValue(site[i + 1]), requiredValue(feature[j]), requiredValue(feature[j + 1]))) return true;
    }
  }
  return false;
}

function pointOnRing(point: number[], ring: number[][]): boolean {
  const closed = closeRing(ring);
  for (let i = 0; i < closed.length - 1; i++) {
    if (orientation(requiredValue(closed[i]), point, requiredValue(closed[i + 1])) === 0 && onSegment(requiredValue(closed[i]), point, requiredValue(closed[i + 1]))) {
      return true;
    }
  }
  return false;
}

function pointInsideOrOnRing(point: number[], ring: number[][]): boolean {
  return pointInRing([requiredValue(point[0]), requiredValue(point[1])], ring) || pointOnRing(point, ring);
}

function ringContainedInSite(siteRing: number[][], featureRing: number[][]): boolean {
  if (siteRing.length < 3 || featureRing.length < 3) return true;
  const feature = closeRing(featureRing);
  for (let i = 0; i < feature.length - 1; i++) {
    const a = requiredValue(feature[i]);
    const b = requiredValue(feature[i + 1]);
    const mid = [(requiredValue(a[0]) + requiredValue(b[0])) / 2, (requiredValue(a[1]) + requiredValue(b[1])) / 2];
    const thirdA = [requiredValue(a[0]) + (requiredValue(b[0]) - requiredValue(a[0])) / 3, requiredValue(a[1]) + (requiredValue(b[1]) - requiredValue(a[1])) / 3];
    const thirdB = [requiredValue(a[0]) + (requiredValue(b[0]) - requiredValue(a[0])) * 2 / 3, requiredValue(a[1]) + (requiredValue(b[1]) - requiredValue(a[1])) * 2 / 3];
    if (![a, mid, thirdA, thirdB].every(p => pointInsideOrOnRing(requiredValue(p), siteRing))) {
      return false;
    }
  }
  return true;
}

function featureFitsSite(feature: GeoJSONFeature | null | undefined, sitePolygon: object | null): boolean {
  if (!feature || !sitePolygon) return Boolean(feature);
  const siteRing = outerRing(sitePolygon as SiteGeometry);
  const featureRing = outerRing(feature.geometry);
  if (!siteRing || !featureRing) return true;
  return ringsOverlap(siteRing, featureRing) && ringContainedInSite(siteRing, featureRing);
}

function scoreParetoCandidate(design: DesignData, designs: DesignData[]): number {
  const xs = designs.map(d => d.objectives[0] || 0);
  const ys = designs.map(d => d.objectives[1] || 0);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const x = ((design.objectives[0] || 0) - xMin) / ((xMax - xMin) || 1);
  const y = ((design.objectives[1] || 0) - yMin) / ((yMax - yMin) || 1);
  return x * 0.72 + y * 0.28 - Math.max(0, design.penalty || 0) * 0.05;
}

function designShapeKey(design: DesignData, feature: GeoJSONFeature | null): string {
  const props = feature?.properties;
  return props?.mass_shape || props?.algorithm || design.algorithm || 'unknown';
}

function designIdentityKey(design: DesignData): string {
  return design.uid || `${design.algorithm || 'unknown'}:${design.id}`;
}

function pickDiverseParetoDesigns(
  designs: DesignData[],
  features: GeoJSONFeature[],
  sitePolygon: object | null,
  limit: number,
): DesignData[] {
  const locationChecked = features.length > 0
    ? designs.filter(d => {
      const feat = features.find(f => matchesDesignFeature(f, d));
      return !feat || featureFitsSite(feat, sitePolygon);
    })
    : designs;
  const candidates = locationChecked.length > 0 ? locationChecked : designs;
  if (candidates.length <= limit) return candidates;

  const ranked = [...candidates]
    .sort((a, b) => scoreParetoCandidate(b, candidates) - scoreParetoCandidate(a, candidates));
  const selected: DesignData[] = [];
  const usedShapes = new Set<string>();

  for (const design of ranked) {
    if (selected.length >= limit) break;
    const feature = features.find(f => matchesDesignFeature(f, design)) || null;
    const key = designShapeKey(design, feature);
    if (usedShapes.has(key)) continue;
    selected.push(design);
    usedShapes.add(key);
  }

  for (const design of ranked) {
    if (selected.length >= limit) break;
    if (!selected.some(d => designIdentityKey(d) === designIdentityKey(design))) {
      selected.push(design);
    }
  }
  return selected;
}

const matchesDesignFeature = (feature: any, design: DesignData) => {
  const props = feature.properties || {};
  if (design.uid && props.design_uid) {
    return props.design_uid === design.uid;
  }
  return props.design_id === design.id
    && (!design.algorithm || props.algorithm === design.algorithm);
};

function normalizeSitePolygon(geometry: SiteGeometry | null | undefined): SiteGeometry | undefined {
  if (!geometry) return undefined;
  if (geometry.type !== 'MultiPolygon') return geometry;
  const coords = geometry.coordinates as number[][][][];
  const largest = largestPolygonCoordinates(coords);
  return largest ? { type: 'Polygon', coordinates: largest as unknown as number[][][] } : undefined;
}

const DesignPage: React.FC = () => {
  const jobState = useDesignJob();
  const stream = useOptimizationStream();
  const [selectedDesign, setSelectedDesign] = useState<DesignData | null>(null);
  const [activePnu, setActivePnu] = useState('');
  const [buildingType, setBuildingType] = useState('공동주택');
  const [algorithm, setAlgorithm] = useState('maas_legal_envelope');
  const [viewTab, setViewTab] = useState<'mass' | 'floor'>('mass');
  const [floorPlanResult, setFloorPlanResult] = useState<FloorPlanResult | null>(null);
  const [floorPlanLoading, setFloorPlanLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [floorPlanIndex, setFloorPlanIndex] = useState(0);
  const [autoFloorPlan, setAutoFloorPlan] = useState(true);
  const [floorAlgorithm, setFloorAlgorithm] = useState('ga');
  const [interactivePreview, setInteractivePreview] = useState<GeoJSONFeature | null>(null);
  const [aestheticOverlay, setAestheticOverlay] = useState<{
    url: string;
    status: string;
    provider: string;
    style: string;
    textureUrl: string | null;
    texturePanelUrls: Record<string, string>;
    texturedGltfUrl: string | null;
  } | null>(null);
  const [aestheticFacadeStyle, setAestheticFacadeStyle] = useState<string | null>(null);
  const [showAllPareto, setShowAllPareto] = useState(false);
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);
  const textureProbe = (process.env.NODE_ENV === 'development') && new URLSearchParams(window.location.search).get('textureProbe') === 'reference';
  const lastAutoDesignKey = useRef<string | null>(null);
  const autoFloorPlanTimer = useRef<number | null>(null);
  const buildingTypeRequestRef = useRef(buildingType);

  const handlePnuSearch = useCallback(async (pnu: string) => {
    setActionError(null);
    setSelectedDesign(null);
    setInteractivePreview(null);
    setFloorPlanResult(null);
    stream.disconnect();
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
      building_type: buildingType,
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
    lastAutoDesignKey.current = null;
    if (autoFloorPlanTimer.current) window.clearTimeout(autoFloorPlanTimer.current);
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
        stream.disconnect();
      } catch (error) {
        setActionError(error instanceof Error ? error.message : '설계 실행 취소 실패');
      }
    }
  }, [jobState.job, stream]);

  const findFeatureForDesign = useCallback((design: DesignData): GeoJSONFeature | null => {
    if (!stream.paretoGeojson?.length) return null;
    return stream.paretoGeojson.find(f => matchesDesignFeature(f, design)) || null;
  }, [stream.paretoGeojson]);

  const runFloorPlan = useCallback(async (design: DesignData, quick: boolean) => {
    if (!stream.paretoGeojson?.length) return;
    const feat = findFeatureForDesign(design);
    if (!feat) return;

    setFloorPlanLoading(true);
    setActionError(null);
    setFloorPlanIndex(0);
    const genOpts = quick
      ? { num_generations: 10, population_size: 15 }
      : { num_generations: 30, population_size: 30 };
    try {
      const rooms = getRoomPreset(buildingType);
      const result = await generateFloorPlan({
        footprint_geojson: feat.geometry,
        rooms,
        cell_size: 3.0,
        algorithm: floorAlgorithm,
        options: genOpts,
      });
      setFloorPlanResult(result);
      if (!quick) setViewTab('floor');
    } catch (e) {
      setActionError(e instanceof Error ? e.message : '평면 생성 실패');
    } finally {
      setFloorPlanLoading(false);
    }
  }, [stream.paretoGeojson, findFeatureForDesign, buildingType, floorAlgorithm]);

  const handleDesignSelect = useCallback((d: DesignData) => {
    setSelectedDesign(d);
    setInteractivePreview(null);
    setAestheticOverlay(null);
    setAestheticFacadeStyle(null);
    setViewTab('mass');
    const designKey = designIdentityKey(d);
    if (autoFloorPlan && stream.paretoGeojson?.length && designKey !== lastAutoDesignKey.current) {
      lastAutoDesignKey.current = designKey;
      if (autoFloorPlanTimer.current) window.clearTimeout(autoFloorPlanTimer.current);
      autoFloorPlanTimer.current = window.setTimeout(() => {
        runFloorPlan(d, true);
      }, 250);
    }
  }, [autoFloorPlan, stream.paretoGeojson, runFloorPlan]);

  const handleAestheticGenerated = useCallback((result: MaasAestheticResult | null, style = '') => {
    const requestedStyle = style.trim();
    if (!result) {
      setAestheticOverlay(null);
      setAestheticFacadeStyle(null);
      return;
    }
    const assets = result.provider_result?.assets || [];
    const generated = assets.find(asset => asset.role === 'generated_facade_image' && asset.url)?.url
      || assets.find(asset => asset.url)?.url;
    const bakeStatus = (result.provider_result?.metadata?.texture_bake as { status?: string } | undefined)?.status;
    const projectionSkipped = bakeStatus === 'skipped'
      || result.provider_result?.issues?.some(issue => issue.code === 'projection_panels_not_texture_ready');
    setAestheticFacadeStyle(projectionSkipped ? null : (requestedStyle || null));
    const texturedGltfUrl = projectionSkipped
      ? null
      : assets.find(asset => asset.role === 'textured_gltf' && asset.url)?.url || null;
    const texturePanelUrls = projectionSkipped ? {} : assets
      .filter(asset => asset.role === 'facade_panel_image' && asset.url && asset.metadata?.view)
      .reduce<Record<string, string>>((acc, asset) => {
        const view = String(asset.metadata?.view || '');
        if (view) acc[view] = asset.url!;
        return acc;
      }, {});
    const reference = result.reference?.url;
    const url = generated || reference;
    const textureUrl = projectionSkipped ? null : generated || (textureProbe ? reference : null);
    if (!url) {
      setAestheticOverlay(null);
      return;
    }
    setAestheticOverlay({
      url,
      provider: result.provider_result?.provider || result.job.provider,
      status: `${result.provider_result?.provider || result.job.provider} · ${result.status}${projectionSkipped ? ' / mesh skipped' : ''}`,
      style: projectionSkipped ? '' : style,
      textureUrl: textureUrl || null,
      texturePanelUrls,
      texturedGltfUrl,
    });
  }, [textureProbe]);

  useEffect(() => () => {
    if (autoFloorPlanTimer.current) window.clearTimeout(autoFloorPlanTimer.current);
  }, []);

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
      <div
        data-testid="design-ai-collaboration-panel"
        data-collapsed={rightPanelCollapsed ? 'true' : 'false'}
        style={{
        width: rightPanelCollapsed ? 52 : 520,
        height: 'calc(100vh - 56px)',
        flexShrink: 0,
        borderLeft: '1px solid #1e293b',
        background: '#0f172a',
        overflowY: 'auto',
        padding: rightPanelCollapsed ? 8 : 12,
        boxSizing: 'border-box',
        transition: 'width 180ms ease',
      }}>
        <div style={{
          display: 'flex',
          justifyContent: rightPanelCollapsed ? 'center' : 'space-between',
          alignItems: 'center',
          gap: 8,
          padding: '4px 2px 10px',
        }}>
          {!rightPanelCollapsed && (
            <div>
              <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 700 }}>
                AI 설계 협업
              </div>
              <div style={{ color: '#64748b', fontSize: 10, marginTop: 3, letterSpacing: '0.03em' }}>
                MAAS Agent Workspace
              </div>
            </div>
          )}
          <button
            type="button"
            data-testid="design-ai-collaboration-toggle"
            onClick={() => setRightPanelCollapsed((collapsed) => !collapsed)}
            title={rightPanelCollapsed ? 'AI 협업 패널 펼치기' : 'AI 협업 패널 접기'}
            aria-label={rightPanelCollapsed ? 'AI 협업 패널 펼치기' : 'AI 협업 패널 접기'}
            style={{
              width: 30,
              height: 30,
              borderRadius: 7,
              border: '1px solid rgba(148,163,184,0.18)',
              background: 'rgba(2,6,23,0.72)',
              color: '#cbd5e1',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: 800,
            }}
          >
            {rightPanelCollapsed ? '<' : '>'}
          </button>
        </div>
        {rightPanelCollapsed ? (
          <div style={{
            writingMode: 'vertical-rl',
            transform: 'rotate(180deg)',
            color: '#93c5fd',
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: '0.08em',
            margin: '12px auto 0',
            whiteSpace: 'nowrap',
          }}>
            AI 협업
          </div>
        ) : activePanelDesign ? (
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
      </div>
    </div>
  );
};

export default DesignPage;
