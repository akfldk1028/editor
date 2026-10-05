import { useState, useCallback } from 'react';
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

export function useDesignJob() {
  const [state, setState] = useState<DesignJobState>({
    job: null,
    constraints: [],
    sitePolygon: null,
    siteArea: null,
    zones: [],
    setbackGeometries: {},
    lawArticles: null,
    loading: false,
    error: null,
  });

  const loadSiteBoundary = useCallback(async (pnu: string) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const result = await getSiteBoundary(pnu);
      setState(prev => ({
        ...prev,
        sitePolygon: result.geometry,
        siteArea: result.area_m2,
        loading: false,
      }));
      return result;
    } catch (e) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: e instanceof Error ? e.message : 'Failed to load boundary',
      }));
      return null;
    }
  }, []);

  const loadConstraints = useCallback(async (params: {
    pnu?: string; zones?: string[]; site_polygon?: object; building_type?: string; include_law_articles?: boolean;
  }) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const result = await getAutoConstraints(params);
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
      setState(prev => ({
        ...prev,
        constraints: result.constraints,
        zones: result.zones || [],
        setbackGeometries: setbacks,
        lawArticles: result.law_articles || null,
        loading: false,
      }));
      return result;
    } catch (e) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: e instanceof Error ? e.message : 'Failed to load constraints',
      }));
      return null;
    }
  }, []);

  const startJob = useCallback(async (params?: { job_spec?: object; pnu?: string; address?: string }) => {
    if (!state.sitePolygon) {
      setState(prev => ({ ...prev, error: 'No site polygon selected' }));
      return null;
    }

    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const jobSpec = params?.job_spec && typeof params.job_spec === 'object'
        ? { ...(params.job_spec as Record<string, unknown>) }
        : {};
      const options = jobSpec.options && typeof jobSpec.options === 'object'
        ? { ...(jobSpec.options as Record<string, unknown>) }
        : {};
      if (!options.parking_road_context) {
        const parkingRoadContext = parkingRoadContextFromSetbacks(state.setbackGeometries);
        if (parkingRoadContext) {
          options.parking_road_context = parkingRoadContext;
        }
      }
      if (Object.keys(options).length > 0) {
        jobSpec.options = options;
      }
      const job = await createJob({
        site_polygon: state.sitePolygon,
        constraints: state.constraints,
        pnu: params?.pnu,
        address: params?.address,
        ...params,
        job_spec: Object.keys(jobSpec).length > 0 ? jobSpec : params?.job_spec,
      });
      setState(prev => ({ ...prev, job, loading: false }));
      return job;
    } catch (e) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: e instanceof Error ? e.message : 'Failed to create job',
      }));
      return null;
    }
  }, [state.sitePolygon, state.constraints, state.setbackGeometries]);

  const reset = useCallback(() => {
    setState({
      job: null,
      constraints: [],
      sitePolygon: null,
      siteArea: null,
      zones: [],
      setbackGeometries: {},
      lawArticles: null,
      loading: false,
      error: null,
    });
  }, []);

  return { ...state, loadSiteBoundary, loadConstraints, startJob, reset };
}
