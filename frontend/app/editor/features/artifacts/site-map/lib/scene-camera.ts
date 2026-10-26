export interface SceneCamera {
  position: [number, number, number]
  heading: number
  pitch: number
  roll: number
}

export function readSceneCamera(viewer: any): SceneCamera | null {
  if (!viewer || viewer.isDestroyed?.()) return null
  const camera = viewer.camera
  const p = camera?.positionWC
  if (!p) return null
  return { position: [p.x, p.y, p.z], heading: camera.heading, pitch: camera.pitch, roll: camera.roll }
}

export function restoreSceneCamera(viewer: any, Cesium: any, pose: SceneCamera): void {
  viewer.camera.setView({ destination: new Cesium.Cartesian3(...pose.position),
    orientation: { heading: pose.heading, pitch: pose.pitch, roll: pose.roll } })
  viewer.scene.requestRender()
}
