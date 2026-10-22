import { describe, expect, it } from 'bun:test'

import { sitePose } from './site-pose'

// 684-1: about 50 m × 50 m (2,500 ㎡) near 37.73° N
const parcel = [127.1078, 37.7298, 127.10837, 37.73025] as const

describe('the camera pose for a parcel', () => {
  it('comes close for a 2,500 ㎡ parcel, far closer than the old fixed 520 m pose', () => {
    const pose = sitePose(parcel)
    expect(pose.height).toBeGreaterThanOrEqual(90)
    expect(pose.height).toBeLessThan(200)
  })

  it('stands south of the parcel so the oblique view faces it', () => {
    const pose = sitePose(parcel)
    expect(pose.lat).toBeLessThan(parcel[1])
    expect(pose.lng).toBeCloseTo((parcel[0] + parcel[2]) / 2, 9)
  })

  it('backs off for a larger site and never past the ceiling', () => {
    const large = sitePose([127.1, 37.72, 127.11, 37.73])
    expect(large.height).toBeGreaterThan(sitePose(parcel).height)
    expect(large.height).toBeLessThanOrEqual(700)
  })
})
