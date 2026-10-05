import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useDesignFloorPlan } from '../features/design/hooks/use-design-floor-plan';
import type { DesignData, GeoJSONFeature } from '../features/design/lib/types';

const feature = { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[127,37],[127.001,37],[127.001,37.001],[127,37]]] } } as GeoJSONFeature;
const features = [feature];
const findFeature = () => feature;
const design = (id: number) => ({ id, uid: String(id), algorithm: 'test' }) as DesignData;
const root = createRoot(document.getElementById('root')!);
function Harness() {
  const [tab, setTab] = useState<'mass' | 'floor'>('mass');
  const [error, setError] = useState<string | null>(null);
  const hook = useDesignFloorPlan({ paretoGeojson: features, findFeatureForDesign: findFeature, buildingType: 'office', setViewTab: setTab, setActionError: setError });
  Object.assign(window, { floorHarness: {
    run: (id: number, quick = false) => { void hook.runFloorPlan(design(id), quick); },
    reset: () => { hook.resetPendingFloorPlan(); hook.setFloorPlanResult(null); setTab('mass'); },
    select: (id: number) => hook.scheduleAutoFloorPlan(design(id)),
    auto: hook.setAutoFloorPlan,
    unmount: () => root.unmount(),
  } });
  return <output id="state">{JSON.stringify({ result: hook.floorPlanResult, loading: hook.floorPlanLoading, tab, error })}</output>;
}
root.render(<Harness />);
