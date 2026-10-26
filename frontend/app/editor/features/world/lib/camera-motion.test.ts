import { expect, test } from 'bun:test'
import { CameraMotion } from './camera-motion'

test('stationary pose releases detail even when Cesium never emits moveEnd', () => {
  const motion = new CameraMotion()
  expect(motion.update(0, [1, 2, 3])).toBe(false)
  expect(motion.update(10, [2, 2, 3])).toBe(true)
  expect(motion.update(150, [2, 2, 3])).toBe(true)
  expect(motion.update(211, [2, 2, 3])).toBe(false)
})
test('continuous translation or rotation keeps detail deferred', () => {
  const motion = new CameraMotion()
  motion.update(0, [0, 0, 0, 1])
  for (let t = 10; t < 1000; t += 10) expect(motion.update(t, [0, 0, 0, t])).toBe(true)
  expect(motion.update(1200, [0, 0, 0, 990])).toBe(false)
})
