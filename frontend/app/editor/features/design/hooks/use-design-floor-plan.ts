import { useState, useCallback, useRef, useEffect } from 'react';
import type { DesignData, FloorPlanResult, GeoJSONFeature } from '../lib/types';
import { generateFloorPlan } from '../lib/api-client';
import { getRoomPreset } from '../lib/room-presets';
import { designIdentityKey } from '../lib/design-selection';

interface DesignFloorPlanInput {
  paretoGeojson: GeoJSONFeature[];
  findFeatureForDesign: (design: DesignData) => GeoJSONFeature | null;
  buildingType: string;
  setViewTab: (tab: 'mass' | 'floor') => void;
  setActionError: (error: string | null) => void;
}

export function useDesignFloorPlan({ paretoGeojson, findFeatureForDesign, buildingType, setViewTab, setActionError }: DesignFloorPlanInput) {
  const [floorPlanResult, setFloorPlanResult] = useState<FloorPlanResult | null>(null);
  const [floorPlanLoading, setFloorPlanLoading] = useState(false);
  const [floorPlanIndex, setFloorPlanIndex] = useState(0);
  const [autoFloorPlan, setAutoFloorPlan] = useState(true);
  const [floorAlgorithm, setFloorAlgorithm] = useState('ga');
  const lastAutoDesignKey = useRef<string | null>(null);
  const autoFloorPlanTimer = useRef<number | null>(null);

  const runFloorPlan = useCallback(async (design: DesignData, quick: boolean) => {
    if (!paretoGeojson?.length) return;
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
        coordinate_frame: 'wgs84',
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
  }, [paretoGeojson, findFeatureForDesign, buildingType, floorAlgorithm]);

  const scheduleAutoFloorPlan = useCallback((d: DesignData) => {
    const designKey = designIdentityKey(d);
    if (autoFloorPlan && paretoGeojson?.length && designKey !== lastAutoDesignKey.current) {
      lastAutoDesignKey.current = designKey;
      if (autoFloorPlanTimer.current) window.clearTimeout(autoFloorPlanTimer.current);
      autoFloorPlanTimer.current = window.setTimeout(() => {
        runFloorPlan(d, true);
      }, 250);
    }
  }, [autoFloorPlan, paretoGeojson, runFloorPlan]);

  const resetPendingFloorPlan = () => {
    lastAutoDesignKey.current = null;
    if (autoFloorPlanTimer.current) window.clearTimeout(autoFloorPlanTimer.current);
  };

  useEffect(() => () => {
    if (autoFloorPlanTimer.current) window.clearTimeout(autoFloorPlanTimer.current);
  }, []);

  return { floorPlanResult, setFloorPlanResult, floorPlanLoading, floorPlanIndex, setFloorPlanIndex, autoFloorPlan, setAutoFloorPlan, floorAlgorithm, setFloorAlgorithm, runFloorPlan, scheduleAutoFloorPlan, resetPendingFloorPlan };
}
