import { expect, test } from 'bun:test'
import { placeSiteCamera } from './site-camera'

const pose = { lng: 127, lat: 36.999, height: 90, pitchDeg: -42, range: 135 }
function fixture() {
  let placed: any
  const viewer = { useDefaultRenderLoop: true, isDestroyed: () => false, scene: { requestRender() {} },
    camera: { positionWC: 1, directionWC: 2, cancelFlight() {}, lookAt: (target: any, offset: any) => { placed = { target, offset } }, lookAtTransform() {} } }
  const C = { Cartesian3: { clone: (p: any) => p, equalsEpsilon: (a: any, b: any) => a === b, fromDegrees: (lon: number, lat: number, height: number) => ({ lon, lat, height }) },
    Math: { toRadians: (v: number) => v * Math.PI / 180 }, Matrix4: { IDENTITY: {} },
    HeadingPitchRange: class { constructor(public heading: number, public pitch: number, public range: number) {} } }
  return { viewer, C, placed: () => placed }
}
test('site camera targets measured elevation and clears a roof at the camera position', async () => {
  const f = fixture()
  expect(await placeSiteCamera(f.viewer, f.C, 127, 37, pose, async () => 93, () => true, () => 250)).toBe(true)
  expect(f.placed().target).toEqual({ lon: 127, lat: 37, height: 93 })
  expect(f.placed().offset.range * Math.sin(42 * Math.PI / 180) + 93).toBeGreaterThanOrEqual(280)
})
test('a delayed elevation reply does not override user navigation or a hidden view', async () => {
  const f = fixture()
  const sampling = async () => { f.viewer.camera.positionWC = 3; return 93 }
  expect(await placeSiteCamera(f.viewer, f.C, 127, 37, pose, sampling, () => true, () => undefined)).toBe(false)
  f.viewer.useDefaultRenderLoop = false
  expect(await placeSiteCamera(f.viewer, f.C, 127, 37, pose, async () => 93, () => true, () => undefined)).toBe(false)
  expect(f.placed()).toBeUndefined()
})

test('startup can place a paused viewer before any globe tiles are requested', async () => {
  const f = fixture()
  f.viewer.useDefaultRenderLoop = false
  expect(await placeSiteCamera(f.viewer, f.C, 127, 37, pose, async () => 93, () => true, () => undefined, true)).toBe(true)
  expect(f.placed().target.height).toBe(93)
  expect(await placeSiteCamera(f.viewer, f.C, 127, 37, pose, async () => 93, () => false, () => undefined, true)).toBe(false)
})
