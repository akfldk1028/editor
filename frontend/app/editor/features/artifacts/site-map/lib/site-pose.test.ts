import { describe, expect, it } from 'bun:test'

import { shouldFrameSite, sitePose } from './site-pose'

// 684-1: about 50 m × 50 m (2,500 ㎡) near 37.73° N
const parcel = [127.1078, 37.7298, 127.10837, 37.73025] as const

describe('site camera placement ownership', () => {
  it('keeps a user zoom when a delayed save confirms the already framed site', () => {
    let placed: string | null = null
    let camera = 'opening'
    const update = (key: string, look: string) => {
      if (shouldFrameSite(placed, key, look)) { placed = key; camera = `framed:${key}` }
    }
    update('gosan', 'site')
    camera = 'user-wheel-zoom'
    update('gosan', 'picked')
    update('gosan', 'saved')
    update('gosan', 'saved')
    expect(camera).toBe('user-wheel-zoom')
  })

  it('frames an explicitly searched or confirmed different site but not a click preview', () => {
    expect(shouldFrameSite('gosan', 'busan', 'picked')).toBe(false)
    expect(shouldFrameSite('gosan', 'busan', 'saved')).toBe(true)
    expect(shouldFrameSite('gosan', 'busan', 'site')).toBe(true)
  })

  it('allows first placement but preserves the existing site on reactivation', () => {
    for (const look of ['site', 'picked', 'saved']) expect(shouldFrameSite(null, 'gosan', look)).toBe(true)
    expect(shouldFrameSite('gosan', 'gosan', 'saved')).toBe(false)
  })
})

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

  it('backs off enough to fit a large site instead of clipping at a fixed altitude', () => {
    const large = sitePose([127.1, 37.72, 127.11, 37.73])
    expect(large.height).toBeGreaterThan(sitePose(parcel).height)
    const pitch = Math.abs(large.pitchDeg) * Math.PI / 180
    const nearCornerDepth = large.height / Math.sin(pitch) - 557 * Math.cos(pitch)
    expect(nearCornerDepth * Math.tan(Math.PI / 6)).toBeGreaterThan(441)
  })

  it('fits an east-west parcel inside a narrow viewport', () => {
    const bounds = [127.1, 37.72, 127.11, 37.7202] as const
    const pose = sitePose(bounds, { aspectRatio: 0.4, fovy: Math.PI / 3 })
    const range = pose.height / Math.sin(Math.abs(pose.pitchDeg) * Math.PI / 180)
    const halfWidth = 440
    const halfViewWidth = range * Math.tan(Math.PI / 6) * 0.4
    expect(halfViewWidth).toBeGreaterThan(halfWidth)
  })

  it('backs away when the camera uses a narrower field of view', () => {
    const normal = sitePose(parcel, { aspectRatio: 1.5, fovy: Math.PI / 3 })
    const narrow = sitePose(parcel, { aspectRatio: 1.5, fovy: Math.PI / 9 })
    expect(narrow.height).toBeGreaterThan(normal.height * 2)
  })
})
