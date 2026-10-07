import React, { useRef, useCallback, useState } from 'react';
import { useVworld3D } from '../../land-map/hooks/use-vworld-3d';
import { WorldControls } from '../../world/components/WorldControls';
import { useWorld3D } from '../../world/hooks/use-world-3d';
import { reverse } from '../../land-map/lib/land-api-client';
import type { GeoJSONFeature, SetbackGeometriesMap } from '../lib/types';
import { clearDatumPlane, renderDatumMarkers } from '../lib/envelopes/datum-plane';
import { clearElevationGrid } from '../lib/envelopes/elevation-grid';
import { visualizeConstraints } from '../lib/api-client';
import { clearMassEntities, renderMassEntities } from '../lib/cesium/mass-entities';
import { extractRing, buildDatumMarkers } from '../lib/site-map-geometry';
import { MASS_PREFIX, getCesium, hiddenBuildingTiles, hideVworldBuildingTiles, flyToGeometryBbox } from '../lib/cesium/site-scene';
import { clearSetbackEntities, renderSetbackEntities } from '../lib/cesium/setback-entities';
import { clearConstraintEntities, renderConstraintEntities } from '../lib/cesium/constraint-entities';
import MassFallback2D from './MassFallback2D';
import { MassInfoOverlay } from './MassInfoOverlay';

interface Props {
  sitePolygon: object | null;
  massFeatures?: GeoJSONFeature[];
  selectedDesignId?: number;
  aestheticOverlayUrl?: string | null;
  aestheticOverlayStatus?: string | null;
  aestheticFacadeStyle?: string | null;
  aestheticFacadeTextureUrl?: string | null;
  aestheticFacadeTexturePanelUrls?: Record<string, string> | null;
  aestheticTexturedGltfUrl?: string | null;
  aestheticPreviewMode?: boolean;
  onParcelClick?: (pnu: string, address: string) => void;
  setbackGeometries?: SetbackGeometriesMap;
}

/** clean = our own world (white masses, diagram ground, no VWorld SDK); vworld = the VWorld 3D SDK as before. */
type Engine = 'clean' | 'vworld';

const SiteMapPanel: React.FC<Props> = React.memo((props) => {
  const [engine, setEngine] = useState<Engine>('clean');
  // A different engine is a different viewer: remount so each keeps its own hooks and cleanup.
  return <SiteMap key={engine} {...props} engine={engine} onEngine={setEngine} />;
});

const SiteMap: React.FC<Props & { engine: Engine; onEngine: (e: Engine) => void }> = ({
  engine,
  onEngine,
  sitePolygon,
  massFeatures,
  selectedDesignId,
  aestheticOverlayUrl,
  aestheticOverlayStatus,
  aestheticFacadeStyle,
  aestheticFacadeTextureUrl,
  aestheticFacadeTexturePanelUrls,
  aestheticTexturedGltfUrl,
  aestheticPreviewMode,
  onParcelClick,
  setbackGeometries,
}) => {
  const mapRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState('');
  const [reversing, setReversing] = useState(false);

  // Ref to break circular dependency: handleMapClick needs highlightParcel/flyTo/viewerRef,
  // but useVworld3D needs onClick (which is handleMapClick).
  const actionsRef = useRef<{
    highlightParcel: (g: object) => void;
    clearHighlight: () => void;
    flyTo: (lng: number, lat: number) => void;
    viewerRef: React.RefObject<any>;
  } | null>(null);

  const handleMapClick = useCallback(async (lng: number, lat: number) => {
    setReversing(true);
    setStatus('필지 조회 중...');
    try {
      const result = await reverse(lng, lat);
      if (result.success && result.pnu) {
        if (result.geometry) {
          actionsRef.current?.highlightParcel(result.geometry);
          if (actionsRef.current?.viewerRef) flyToGeometryBbox(actionsRef.current.viewerRef, result.geometry);
        } else {
          actionsRef.current?.flyTo(lng, lat);
        }
        onParcelClick?.(result.pnu, result.address || '');
        setStatus(result.address || result.pnu);
      } else {
        setStatus(result.error || '필지 정보 없음');
      }
    } catch {
      setStatus('필지 조회 실패');
    } finally {
      setReversing(false);
    }
  }, [onParcelClick]);

  // engine is fixed for this component's life (the parent remounts on change), so the hook order never changes.
  const use3D = engine === 'clean' ? useWorld3D : useVworld3D;
  const map = use3D({ target: mapRef, onClick: handleMapClick });
  const { ready, loading, error, highlightParcel, clearHighlight, flyTo, setBuildingsVisible, viewerRef } = map;
  const world = engine === 'clean' ? (map as ReturnType<typeof useWorld3D>) : null;

  actionsRef.current = { highlightParcel, clearHighlight, flyTo, viewerRef };

  React.useEffect(() => {
    if (!ready || !viewerRef.current) return;
    const viewer = viewerRef.current;
    const depthTest = viewer.scene?.globe?.depthTestAgainstTerrain;
    return () => {
      if (viewer.isDestroyed?.()) return;
      clearMassEntities(viewer, MASS_PREFIX);
      clearSetbackEntities(viewer);
      clearConstraintEntities(viewer);
      clearDatumPlane(viewer);
      clearElevationGrid(viewer);
      clearHighlight();
      setBuildingsVisible(true);
      for (const [tile, visible] of hiddenBuildingTiles.get(viewer) ?? []) {
        if (!tile.isDestroyed?.()) tile.show = visible;
      }
      hiddenBuildingTiles.delete(viewer);
      if (viewer.scene?.globe) viewer.scene.globe.depthTestAgainstTerrain = depthTest;
      viewer.scene?.requestRender?.();
    };
  }, [ready, viewerRef, clearHighlight, setBuildingsVisible]);

  // Clean world: the flat ground stands at the site's §119 datum so the mass (placed at its datum) stands on it.
  const datumLevel = setbackGeometries?.datum_result?.parcel_datum_m ?? setbackGeometries?.datum_result?.elevation_m;
  React.useEffect(() => {
    if (ready && world && typeof datumLevel === 'number') world.setGroundLevel(datumLevel);
  }, [ready, world, datumLevel]);

  // Highlight + flyTo when sitePolygon changes
  React.useEffect(() => {
    if (!sitePolygon || !ready) return;
    const hasSetbacks = setbackGeometries && Object.keys(setbackGeometries).length > 0;
    if (hasSetbacks) {
      clearHighlight();
    } else {
      highlightParcel(sitePolygon);
    }
    flyToGeometryBbox(viewerRef, sitePolygon);
  }, [sitePolygon, setbackGeometries, ready, highlightParcel, clearHighlight, viewerRef]);

  // Render 3D building mass when features change + hide existing Vworld buildings
  React.useEffect(() => {
    if (!ready) return;
    const viewer = viewerRef.current;
    const timers: number[] = [];
    const Cesium = getCesium();
    if (!viewer || !Cesium) return;

    const hasSetbacks = setbackGeometries && Object.keys(setbackGeometries).length > 0;
    // 매스는 정북일조 평균수평면이 아니라 대지 자체 §119 datum 위에 배치한다.
    const datumZ = setbackGeometries?.datum_result?.parcel_datum_m
      ?? setbackGeometries?.datum_result?.elevation_m;
    if (massFeatures && massFeatures.length > 0) {
      setBuildingsVisible(false);
      hideVworldBuildingTiles(viewer, Cesium);
      timers.push(window.setTimeout(() => { setBuildingsVisible(false); hideVworldBuildingTiles(viewer, Cesium); }, 800));
      timers.push(window.setTimeout(() => { setBuildingsVisible(false); hideVworldBuildingTiles(viewer, Cesium); }, 2200));
      renderMassEntities({
        viewer,
        Cesium,
        features: massFeatures,
        entityPrefix: MASS_PREFIX,
        selectedId: selectedDesignId,
        datumZ,
        aestheticOverlayUrl,
        aestheticOverlayStatus,
        aestheticFacadeStyle,
        aestheticFacadeTextureUrl,
        aestheticFacadeTexturePanelUrls,
        aestheticTexturedGltfUrl,
      });
    } else if (hasSetbacks) {
      // 규제선만 있어도 기존 건물 숨기기 (Wall이 건물에 가려지지 않도록)
      setBuildingsVisible(false);
      hideVworldBuildingTiles(viewer, Cesium);
      timers.push(window.setTimeout(() => { setBuildingsVisible(false); hideVworldBuildingTiles(viewer, Cesium); }, 800));
      timers.push(window.setTimeout(() => { setBuildingsVisible(false); hideVworldBuildingTiles(viewer, Cesium); }, 2200));
      clearMassEntities(viewer, MASS_PREFIX);
    } else {
      clearMassEntities(viewer, MASS_PREFIX);
      setBuildingsVisible(true);
    }
    return () => timers.forEach(window.clearTimeout);
  }, [massFeatures, selectedDesignId, aestheticOverlayUrl, aestheticOverlayStatus, aestheticFacadeStyle, aestheticFacadeTextureUrl, aestheticFacadeTexturePanelUrls, aestheticTexturedGltfUrl, setbackGeometries, ready, viewerRef, setBuildingsVisible]);

  // Render setback geometry lines (regulation boundaries)
  React.useEffect(() => {
    if (!ready) return;
    const viewer = viewerRef.current;
    const timers: number[] = [];
    const Cesium = getCesium();
    if (!viewer || !Cesium) return;
    try {
      (window as unknown as { __arrDesignSetbackGeometries?: SetbackGeometriesMap | null }).__arrDesignSetbackGeometries = setbackGeometries ?? null;
    } catch {
      // Debug/export helper only.
    }

    if (setbackGeometries && Object.keys(setbackGeometries).length > 0) {
      if (aestheticPreviewMode) {
        clearHighlight();
        clearSetbackEntities(viewer);
        clearConstraintEntities(viewer);
        clearDatumPlane(viewer);
        clearElevationGrid(viewer);
        hideVworldBuildingTiles(viewer, Cesium);
        try {
          viewer.scene?.requestRender?.();
        } catch { /* ignore */ }
        return;
      }
      clearHighlight();
      clearConstraintEntities(viewer);
      // Terrain이 envelope polygon (H=10~50m)을 가리는 것 방지 — depth test 끔.
      // Vworld terrain이 parcel 위치에서 10.18m 고도라 H=10m envelope가 묻힘.
      try {
        if (viewer.scene?.globe) viewer.scene.globe.depthTestAgainstTerrain = false;
      } catch { /* ignore */ }
      const ring = sitePolygon ? extractRing(sitePolygon as { type: string; coordinates: any }) : null;
      renderSetbackEntities(viewer, Cesium, setbackGeometries, ring);
      hideVworldBuildingTiles(viewer, Cesium);
      timers.push(window.setTimeout(() => hideVworldBuildingTiles(viewer, Cesium), 800));
      timers.push(window.setTimeout(() => hideVworldBuildingTiles(viewer, Cesium), 2200));
      // NOTE: 카메라 이동은 sitePolygon useEffect의 flyToGeometryBbox(line 407)이
      // 이미 parcel 위치로 이동시킴. zoomTo(entities)는 vworld map 자체 카메라 모션과
      // race condition 발생해 기존 위치 잃어버림 → entities 위치 이동 호출 제거.
      // 사용자가 carcel에 줌인 되어 있으면 envelope wall(H=10m)/slope(H=50m) 자동 보임.

      // Plan PNG와 동일한 희소 법규 기준점만 표시한다.
      // 전체 표고 격자/넓은 datum 면은 법규 기준점과 혼동되므로 기본 표시하지 않는다.
      clearDatumPlane(viewer);
      renderDatumMarkers(viewer, Cesium, buildDatumMarkers(setbackGeometries, ring));

      // 자동 표고 격자는 법규 기준면과 혼동되므로 /design에서는 기본 표시하지 않는다.
      clearElevationGrid(viewer);
    } else {
      clearDatumPlane(viewer);
      clearElevationGrid(viewer);
    }
    return () => timers.forEach(window.clearTimeout);
  }, [setbackGeometries, sitePolygon, ready, viewerRef, clearHighlight, aestheticPreviewMode]);

  // visualizeConstraints fallback — setbackGeometries 비어있을 때 임의 polygon에
  // envelope/setback 시각 자동 생성 (Flexity 광고의 빨간 공지 + 녹색 사선 base 매칭).
  // PNU 검색 성공 시 setbackGeometries가 채워지므로 이 fallback은 트리거 X.
  React.useEffect(() => {
    if (!ready) return;
    const viewer = viewerRef.current;
    const Cesium = getCesium();
    if (!viewer || !Cesium) return;

    const hasSetbacks = setbackGeometries && Object.keys(setbackGeometries).length > 0;
    let cancelled = false;
    if (sitePolygon && !hasSetbacks) {
      visualizeConstraints({ site_polygon: sitePolygon })
        .then(result => {
          if (!cancelled) renderConstraintEntities(viewer, Cesium, result);
        })
        .catch(err => console.warn('[visualizeConstraints] fallback failed:', err));
    } else {
      clearConstraintEntities(viewer);
    }
    return () => {
      cancelled = true;
      if (!viewer.isDestroyed?.()) clearConstraintEntities(viewer);
    };
  }, [sitePolygon, setbackGeometries, ready, viewerRef]);

  return (
    <div style={{
      width: '100%', height: '100%',
      position: 'relative', borderRadius: 12, overflow: 'hidden',
      boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
    }}>
      <div
        ref={mapRef}
        id="vworld-3d-design"
        style={{ width: '100%', height: '100%', background: engine === 'clean' ? '#f7f7f5' : '#0f172a' }}
      />

      {/* Loading overlay */}
      {loading && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(15,23,42,0.85)', zIndex: 10,
          backdropFilter: 'blur(8px)',
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{
              width: 36, height: 36, margin: '0 auto 12px',
              border: '3px solid #334155', borderTopColor: '#3b82f6',
              borderRadius: '50%',
              animation: 'spin 1s linear infinite',
            }} />
            <div style={{ color: '#94a3b8', fontSize: 13 }}>3D 지도 로딩 중...</div>
          </div>
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* Error overlay */}
      {error && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: '#0f172a', zIndex: 10,
        }}>
          {massFeatures?.length ? (
            <MassFallback2D
              sitePolygon={sitePolygon}
              massFeatures={massFeatures}
              selectedDesignId={selectedDesignId}
              reason={error}
            />
          ) : (
            <div style={{ color: '#f87171', fontSize: 13 }}>{error}</div>
          )}
        </div>
      )}

      {/* Engine toggle — our clean world (default) or the VWorld 3D SDK */}
      <div style={{ position: 'absolute', top: 12, right: 12, zIndex: 11, display: 'flex', gap: 4,
        background: 'rgba(255,255,255,0.92)', borderRadius: 8, padding: 3, fontSize: 12 }}>
        {([['clean', '깔끔한 3D'], ['vworld', '브이월드']] as const).map(([key, label]) => (
          <button key={key} type="button" onClick={() => onEngine(key)}
            style={{ padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: engine === key ? '#1f2937' : 'transparent', color: engine === key ? '#fff' : '#374151' }}>
            {label}
          </button>
        ))}
      </div>
      {world && <WorldControls world={world} title="주변 맥락" compact
        className="absolute bottom-14 right-3 z-10 flex flex-col gap-0.5 rounded-md bg-white/90 px-2 py-1 text-[11px] text-neutral-800 shadow" />}

      {/* Mass info overlay — shows building stats */}
      <MassInfoOverlay massFeatures={massFeatures} />

      {/* Status bar — shows parcel info after click */}
      {(status || reversing) && (
        <div style={{
          position: 'absolute', bottom: 12, left: 12, right: 12,
          padding: '8px 14px',
          background: 'rgba(15,23,42,0.88)', borderRadius: 8,
          border: '1px solid rgba(255,255,255,0.06)',
          backdropFilter: 'blur(8px)',
          fontSize: 12, color: reversing ? '#94a3b8' : '#e2e8f0',
          zIndex: 10,
        }}>
          {reversing ? '필지 조회 중...' : status}
        </div>
      )}

      {/* Hint — shown when map is ready but no parcel selected */}
      {ready && !status && !massFeatures?.length && (
        <div style={{
          position: 'absolute', top: 12, left: 12,
          padding: '6px 12px',
          background: 'rgba(15,23,42,0.85)', borderRadius: 8,
          border: '1px solid rgba(255,255,255,0.06)',
          backdropFilter: 'blur(8px)',
          fontSize: 11, color: '#64748b',
          zIndex: 10,
        }}>
          지적도 필지를 클릭하여 대지를 선택하세요
        </div>
      )}
    </div>
  );
};

SiteMapPanel.displayName = 'SiteMapPanel';
SiteMap.displayName = 'SiteMap';
export default SiteMapPanel;
