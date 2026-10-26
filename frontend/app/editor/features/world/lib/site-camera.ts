/* eslint-disable @typescript-eslint/no-explicit-any */
export async function placeSiteCamera(viewer: any, C: any, lon: number, lat: number,
  pose: { lng: number; lat: number; height: number; pitchDeg: number; range: number },
  sampleHeight: (lon: number, lat: number) => Promise<number>, live: () => boolean,
  roofAt: (lon: number, lat: number) => number | undefined, allowPaused = false): Promise<boolean> {
  viewer.camera.cancelFlight()
  const position = C.Cartesian3.clone(viewer.camera.positionWC)
  const direction = C.Cartesian3.clone(viewer.camera.directionWC)
  const [ground, cameraGround] = await Promise.all([sampleHeight(lon, lat), sampleHeight(pose.lng, pose.lat)])
  if (!live() || viewer.isDestroyed() || (!allowPaused && !viewer.useDefaultRenderLoop)) return false
  if (!C.Cartesian3.equalsEpsilon(position, viewer.camera.positionWC, 1e-10)
    || !C.Cartesian3.equalsEpsilon(direction, viewer.camera.directionWC, 1e-10)) return false
  if (!Number.isFinite(ground) || !Number.isFinite(cameraGround)) throw new Error('No site elevation')
  const clearance = Math.max(cameraGround, roofAt(pose.lng, pose.lat) ?? cameraGround) + 30
  const range = Math.max(pose.range, (clearance - ground) / Math.sin(Math.abs(pose.pitchDeg) * Math.PI / 180))
  viewer.camera.lookAt(C.Cartesian3.fromDegrees(lon, lat, ground), new C.HeadingPitchRange(0, C.Math.toRadians(pose.pitchDeg), range))
  viewer.camera.lookAtTransform(C.Matrix4.IDENTITY)
  viewer.scene.requestRender()
  return true
}
