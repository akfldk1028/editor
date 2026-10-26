import { expect, test } from 'bun:test'
import { visibleBox } from './context-cells'

test('building view covers screen edges beyond the old one-kilometre clamp', () => {
  const viewer = { canvas: { clientWidth: 1000, clientHeight: 1000 }, camera: {
    pickEllipsoid: ({ x, y }: { x: number; y: number }) => ({ longitude: 126 + x / 1000, latitude: 38 - y / 1000 }),
  } }
  const C = { Cartesian2: class { constructor(public x: number, public y: number) {} },
    Cartographic: { fromCartesian: (p: unknown) => p }, Math: { toDegrees: (v: number) => v } }
  const view = visibleBox(viewer, C)!
  expect(view.box[0]).toBeLessThanOrEqual(126)
  expect(view.box[2]).toBeGreaterThanOrEqual(127)
  expect(view.box[1]).toBeLessThanOrEqual(37)
  expect(view.box[3]).toBeGreaterThanOrEqual(38)
})

test('a tilted view includes the ground above the first successful fixed sample', () => {
  const viewer = { canvas: { clientWidth: 1000, clientHeight: 1000 }, camera: {
    pickEllipsoid: ({ x, y }: { x: number; y: number }) => y < 350 ? null : { longitude: 126 + x / 1000, latitude: 38 - y / 1000 },
  } }
  const C = { Cartesian2: class { constructor(public x: number, public y: number) {} },
    Cartographic: { fromCartesian: (p: unknown) => p }, Math: { toDegrees: (v: number) => v } }
  expect(visibleBox(viewer, C)!.box[3]).toBeGreaterThan(37.64)
})
