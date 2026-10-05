import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useInteractiveDesign } from '../features/design/hooks/use-interactive-design';
import type { DesignData, GeoJSONFeature, MaasAestheticResult } from '../features/design/lib/types';
const root = createRoot(document.getElementById('root')!);
function Harness() {
  const [context, setContext] = useState({ job: 'job-old', uid: 'old-uid' });
  const [applied, setApplied] = useState<GeoJSONFeature | null>(null);
  const [texture, setTexture] = useState<MaasAestheticResult | null>(null);
  const design = useMemo(() => ({ id: 0, uid: context.uid, algorithm: 'maas', inputs: [] }) as unknown as DesignData, [context]);
  const mass = useMemo(() => ({ type: 'Feature', properties: { design_id: 0, design_uid: context.uid }, geometry: { type: 'Polygon', coordinates: [[[127,37],[127.001,37],[127.001,37.001],[127,37]]] } }) as GeoJSONFeature, [context]);
  const hook = useInteractiveDesign({ jobId: context.job, design, massGeojson: mass, constraints: [], sitePolygon: mass.geometry, siteArea: 100,
    buildingType: 'office', algorithm: 'maas', onPreviewCandidate: setApplied, onAestheticGenerated: setTexture });
  Object.assign(window, { interactiveHarness: { ...hook, switchContext: (next = { job: 'job-new', uid: 'new-uid' }) => setContext(next), unmount: () => root.unmount() } });
  return <output id="state">{JSON.stringify({ context, applied, texture, result: hook.result, preview: hook.preview, aesthetic: hook.aesthetic,
    error: hook.error, message: hook.message, loading: [hook.loading, hook.previewLoading, hook.operationLoading, hook.aestheticLoading] })}</output>;
}
root.render(<Harness />);
