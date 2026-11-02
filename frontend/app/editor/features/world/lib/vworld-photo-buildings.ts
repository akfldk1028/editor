/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * VWorld's textured building models, drawn in our own viewer on our terrain. These are the national 3D Tiles
 * (b3dm, one root with external per-district tilesets) that VWorld WebGL API 3.0 itself streams. Measured on
 * 2026-11-02: footprints and heights coincide with our buildings, Gangnam settles in ~2.1 s.
 *
 * Internal review only: this reads VWorld's CDN directly, outside its keyed API, which is not cleared for service.
 */
export const VWORLD_PHOTO_TILESET = 'https://cdn.vworld.kr/TDServer/services/map4/TG9ENA.json'

/** Adds the textured buildings and hides ours; the returned function restores the scene. */
export function showVworldPhotoBuildings(viewer: any, C: any, failed: (message: string) => void) {
  let tileset: any, disposed = false, oursHidden = true
  const ours = viewer.buildingTiles
  ours?.setShow?.(false)
  void C.Cesium3DTileset.fromUrl(VWORLD_PHOTO_TILESET, {
    maximumScreenSpaceError: 16, preloadFlightDestinations: false, cullRequestsWhileMoving: false,
    cacheBytes: 512 * 1024 * 1024,
  }).then((made: any) => {
    if (disposed || viewer.isDestroyed()) { made.destroy(); return }
    tileset = made
    viewer.scene.primitives.add(tileset)
    // Same requestRenderMode handling as our buildings: keep frames coming until the visible tiles have loaded.
    // VWorld has no models in some districts (e.g. 의정부 산곡동): where the settled view draws none, ours stay.
    const remove = viewer.scene.postRender.addEventListener(() => {
      if (!tileset || tileset.isDestroyed()) return
      if (!tileset.tilesLoaded) { viewer.scene.requestRender(); return }
      const covered = tileset._selectedTiles?.some((tile: any) => tile.content?.featuresLength > 0) ?? true
      // Only on change: setShow requests a render, which would otherwise loop through this listener.
      if (covered === oursHidden) return
      oursHidden = covered; ours?.setShow?.(!covered)
    })
    tileset.__remove = remove
    viewer.scene.requestRender()
  }).catch((error: unknown) => { if (!disposed) failed(`실사 건물: ${error instanceof Error ? error.message : String(error)}`) })
  return () => {
    disposed = true
    if (viewer.isDestroyed()) return
    if (tileset) { tileset.__remove?.(); viewer.scene.primitives.remove(tileset) }
    ours?.setShow?.(true)
    viewer.scene.requestRender()
  }
}
