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
  const requestRef = useRef<AbortController | null>(null);

  const cancelPending = useCallback(() => {
    if (autoFloorPlanTimer.current !== null) window.clearTimeout(autoFloorPlanTimer.current);
    autoFloorPlanTimer.current = null;
    requestRef.current?.abort();
    requestRef.current = null;
  }, []);

  const resetPendingFloorPlan = useCallback(() => {
    cancelPending();
    lastAutoDesignKey.current = null;
    setFloorPlanLoading(false);
  }, [cancelPending]);

  const runFloorPlan = useCallback(async (design: DesignData, quick: boolean) => {
    resetPendingFloorPlan();
    if (!paretoGeojson?.length) return;
    const feat = findFeatureForDesign(design);
    if (!feat) return;

    const controller = new AbortController();
    requestRef.current = controller;
    lastAutoDesignKey.current = designIdentityKey(design);
    const isCurrent = () => requestRef.current === controller && !controller.signal.aborted;
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
      }, controller.signal);
      if (!isCurrent()) return;
      setFloorPlanResult(result);
      if (!quick) setViewTab('floor');
    } catch (e) {
      if (!isCurrent()) return;
      lastAutoDesignKey.current = null;
      setActionError(e instanceof Error ? e.message : '평면 생성 실패');
    } finally {
      if (isCurrent()) {
        requestRef.current = null;
        setFloorPlanLoading(false);
      }
    }
  }, [paretoGeojson, findFeatureForDesign, buildingType, floorAlgorithm, resetPendingFloorPlan, setActionError, setViewTab]);

  const scheduleAutoFloorPlan = useCallback((d: DesignData) => {
    const designKey = designIdentityKey(d);
    if (designKey === lastAutoDesignKey.current) return;
    resetPendingFloorPlan();
    setFloorPlanResult(null);
    if (autoFloorPlan && paretoGeojson?.length) {
      lastAutoDesignKey.current = designKey;
      autoFloorPlanTimer.current = window.setTimeout(() => {
        autoFloorPlanTimer.current = null;
        void runFloorPlan(d, true);
      }, 250);
    }
  }, [autoFloorPlan, paretoGeojson, runFloorPlan, resetPendingFloorPlan]);

  useEffect(() => {
    if (!autoFloorPlan && autoFloorPlanTimer.current !== null) resetPendingFloorPlan();
  }, [autoFloorPlan, resetPendingFloorPlan]);

  useEffect(() => cancelPending, [cancelPending]);

  return { floorPlanResult, setFloorPlanResult, floorPlanLoading, floorPlanIndex, setFloorPlanIndex, autoFloorPlan, setAutoFloorPlan, floorAlgorithm, setFloorAlgorithm, runFloorPlan, scheduleAutoFloorPlan, resetPendingFloorPlan };
}
