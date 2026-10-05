import { useState, useCallback, useEffect, useRef } from 'react';
import type { DesignJob, Constraint, SetbackGeometriesMap, LawSearchResult } from '../lib/types';
import { createJob, getAutoConstraints, getSiteBoundary } from '../lib/api-client';

interface DesignJobState {
  job: DesignJob | null;
  constraints: Constraint[];
  sitePolygon: object | null;
  siteArea: number | null;
  zones: string[];
  setbackGeometries: SetbackGeometriesMap;
  lawArticles: LawSearchResult | null;
  loading: boolean;
  error: string | null;
}

function parkingRoadContextFromSetbacks(setbackGeometries: SetbackGeometriesMap) {
  const roadFrontages = Array.isArray(setbackGeometries?.road_frontages)
    ? setbackGeometries.road_frontages as Array<Record<string, unknown>>
    : [];
  const widths = roadFrontages
    .map(frontage => Number(frontage.roadWidthM ?? frontage.road_width_m ?? 0))
    .filter(width => Number.isFinite(width) && width > 0);
  if (!roadFrontages.length && !widths.length) return undefined;
  return {
    road_width_m: widths.length ? Math.max(...widths) : undefined,
    road_frontages: roadFrontages.map(frontage => ({
      geometry: frontage.geometry,
      sharedEdge: frontage.sharedEdge ?? frontage.shared_edge,
      roadCenterline: frontage.roadCenterline ?? frontage.road_centerline,
      roadWidthM: frontage.roadWidthM ?? frontage.road_width_m,
      landCategory: frontage.landCategory ?? frontage.land_category,
    })),
  };
}

function emptyState(): DesignJobState {
  return {
    job: null,
    constraints: [],
    sitePolygon: null,
    siteArea: null,
    zones: [],
    setbackGeometries: {},
    lawArticles: null,
    loading: false,
    error: null,
  };
}

type RequestKind = 'boundary' | 'constraints' | 'job';

export function useDesignJob() {
  const [state, setState] = useState<DesignJobState>(emptyState);
  const stateRef = useRef(state);
  const mountedRef = useRef(true);
  const pnuRef = useRef<string | null>(null);
  const requestsRef = useRef<Record<RequestKind, AbortController | null>>({ boundary: null, constraints: null, job: null });

  const updateState = useCallback((update: (previous: DesignJobState) => DesignJobState) => {
    if (!mountedRef.current) return;
    // Event callbacks can run again before React renders the cleared parcel.
    stateRef.current = update(stateRef.current);
    setState(stateRef.current);
  }, []);

  const abortRequests = useCallback((kinds: RequestKind[]) => {
    for (const kind of kinds) {
      requestsRef.current[kind]?.abort();
      requestsRef.current[kind] = null;
    }
  }, []);

  const ownsRequest = useCallback((kind: RequestKind, controller: AbortController) =>
    mountedRef.current && requestsRef.current[kind] === controller && !controller.signal.aborted, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRequests(['boundary', 'constraints', 'job']);
    };
  }, [abortRequests]);

  const loadSiteBoundary = useCallback(async (pnu: string) => {
    if (!mountedRef.current) return null;
    abortRequests(['boundary', 'constraints', 'job']);
    pnuRef.current = pnu;
    const controller = new AbortController();
    requestsRef.current.boundary = controller;
    updateState(() => ({ ...emptyState(), loading: true }));
    try {
      const result = await getSiteBoundary(pnu, controller.signal);
      if (!ownsRequest('boundary', controller)) return null;
      requestsRef.current.boundary = null;
      pnuRef.current = result.pnu || pnu;
      updateState(prev => ({
        ...prev,
        sitePolygon: result.geometry,
        siteArea: result.area_m2,
        loading: false,
      }));
      return result;
    } catch (e) {
      if (!ownsRequest('boundary', controller)) return null;
      requestsRef.current.boundary = null;
      updateState(prev => ({
        ...prev,
        loading: false,
        error: e instanceof Error ? e.message : 'Failed to load boundary',
      }));
      return null;
    }
  }, [abortRequests, ownsRequest, updateState]);

  const loadConstraints = useCallback(async (params: {
    pnu?: string; zones?: string[]; site_polygon?: object; building_type?: string; include_law_articles?: boolean;
  }) => {
    if (!mountedRef.current || !stateRef.current.sitePolygon || requestsRef.current.boundary
        || (params.pnu && params.pnu !== pnuRef.current)) return null;
    abortRequests(['constraints', 'job']);
    const controller = new AbortController();
    requestsRef.current.constraints = controller;
    updateState(prev => ({ ...prev, job: null, constraints: [], zones: [],
      setbackGeometries: {}, lawArticles: null, loading: true, error: null }));
    try {
      const result = await getAutoConstraints(params, controller.signal);
      if (!ownsRequest('constraints', controller)) return null;
      requestsRef.current.constraints = null;
      const setbacks = result.setback_geometries || {};
      const datum = setbacks.datum_result;
      const sunlight = setbacks.sunlight_envelope;
      const daylight = setbacks.daylight_diagonal_envelope;
      const roadFrontages = setbacks.road_frontages as unknown as Array<{
        roadWidthM?: number;
        roadCenterline?: unknown;
      }> | undefined;
      console.info('[Design][LegalQA] constraints', {
        pnu: params.pnu,
        zones: result.zones || [],
        datum: datum ? {
          parcel_datum_m: datum.parcel_datum_m,
          road_datum_m: datum.road_datum_m,
          neighbor_datum_m: datum.neighbor_datum_m,
          neighbor_avg_datum_m: datum.neighbor_avg_datum_m,
          source: datum.elevation_source,
          parcel_samples: datum.parcel_segments?.length ?? 0,
          road_samples: datum.road_samples?.length ?? 0,
          neighbor_samples: datum.neighbor_segments?.length ?? 0,
        } : null,
        sunlight: sunlight ? {
          formula: 'H <= 2D after 10m base height; base setback 1.5m',
          slope_vertical_horizontal: `${sunlight.slope ?? 2}:1`,
          datum_elevation_m: sunlight.datum_elevation_m,
          datum_case: sunlight.datum_case,
          walls: sunlight.walls?.length ?? 0,
          mesh_layers: sunlight.envelope_layers?.length ?? 0,
        } : null,
        daylight: daylight ? {
          formula: `H <= ${(daylight as { multiplier?: number }).multiplier ?? 2}D`,
          multiplier: (daylight as { multiplier?: number }).multiplier,
          walls: daylight.walls?.length ?? 0,
        } : null,
        road_frontages: roadFrontages?.map((r, i) => ({
          i,
          width_m: r.roadWidthM,
          has_centerline: Boolean(r.roadCenterline),
        })) ?? [],
      });
      updateState(prev => ({
        ...prev,
        constraints: result.constraints,
        zones: result.zones || [],
        setbackGeometries: setbacks,
        lawArticles: result.law_articles || null,
        loading: false,
      }));
      return result;
    } catch (e) {
      if (!ownsRequest('constraints', controller)) return null;
      requestsRef.current.constraints = null;
      updateState(prev => ({
        ...prev,
        loading: false,
        error: e instanceof Error ? e.message : 'Failed to load constraints',
      }));
      return null;
    }
  }, [abortRequests, ownsRequest, updateState]);

  const startJob = useCallback(async (params?: { job_spec?: object; pnu?: string; address?: string }) => {
    if (!mountedRef.current) return null;
    const snapshot = stateRef.current;
    if (!snapshot.sitePolygon || (params?.pnu && params.pnu !== pnuRef.current)) {
      updateState(prev => ({ ...prev, error: 'No matching site polygon selected' }));
      return null;
    }
    if (requestsRef.current.boundary || requestsRef.current.constraints) {
      updateState(prev => ({ ...prev, error: 'Site context is still loading' }));
      return null;
    }

    abortRequests(['job']);
    const controller = new AbortController();
    requestsRef.current.job = controller;
    updateState(prev => ({ ...prev, job: null, loading: true, error: null }));
    try {
      const jobSpec = params?.job_spec && typeof params.job_spec === 'object'
        ? { ...(params.job_spec as Record<string, unknown>) }
        : {};
      const options = jobSpec.options && typeof jobSpec.options === 'object'
        ? { ...(jobSpec.options as Record<string, unknown>) }
        : {};
      if (!options.parking_road_context) {
        const parkingRoadContext = parkingRoadContextFromSetbacks(snapshot.setbackGeometries);
        if (parkingRoadContext) {
          options.parking_road_context = parkingRoadContext;
        }
      }
      if (Object.keys(options).length > 0) {
        jobSpec.options = options;
      }
      const job = await createJob({
        site_polygon: snapshot.sitePolygon,
        constraints: snapshot.constraints,
        pnu: params?.pnu,
        address: params?.address,
        ...params,
        job_spec: Object.keys(jobSpec).length > 0 ? jobSpec : params?.job_spec,
      }, controller.signal);
      if (!ownsRequest('job', controller)) return null;
      requestsRef.current.job = null;
      updateState(prev => ({ ...prev, job, loading: false }));
      return job;
    } catch (e) {
      if (!ownsRequest('job', controller)) return null;
      requestsRef.current.job = null;
      updateState(prev => ({
        ...prev,
        loading: false,
        error: e instanceof Error ? e.message : 'Failed to create job',
      }));
      return null;
    }
  }, [abortRequests, ownsRequest, updateState]);

  const reset = useCallback(() => {
    abortRequests(['boundary', 'constraints', 'job']);
    pnuRef.current = null;
    updateState(emptyState);
  }, [abortRequests, updateState]);

  return { ...state, loadSiteBoundary, loadConstraints, startJob, reset };
}
