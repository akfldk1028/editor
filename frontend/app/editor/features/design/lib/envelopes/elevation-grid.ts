/**
 * 주변 표고 격자 entity 정리 (Cesium 3D).
 *
 * 격자를 그리던 `renderElevationGrid`와 그 백엔드(`/land/elevation-grid/`)는
 * 호출자가 없어 제거됐다. 남은 것은 과거 entity를 지우는 정리 함수뿐이다.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

export const ELEVATION_GRID_PREFIX = 'design-elev-grid-';

/** Viewer에서 격자 entity 제거 (re-render 전 정리). */
export function clearElevationGrid(viewer: any): void {
  if (!viewer) return;
  const toRemove: any[] = [];
  for (const e of viewer.entities.values) {
    if (typeof e.id === 'string' && e.id.startsWith(ELEVATION_GRID_PREFIX)) {
      toRemove.push(e);
    }
  }
  for (const e of toRemove) viewer.entities.remove(e);
}
