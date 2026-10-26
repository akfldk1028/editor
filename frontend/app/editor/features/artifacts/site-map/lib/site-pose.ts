/**
 * Where the 3D camera stands to show a parcel: high and far enough that the whole parcel and a ring of its
 * neighbours fill the view, never the fixed 520 m pose that left a 2,500 ㎡ parcel a speck on the screen.
 * Pure; the hook turns it into a Cesium flight.
 */
const M_PER_DEG_LAT = 111_320
const PITCH_DEG = -42
/** Leave room around the parcel for its immediate surroundings. */
const FILL = 0.65
const MIN_HEIGHT_M = 90

export interface SitePose {
  /** Camera position: the parcel centre moved south, so a north-facing oblique view looks at it. */
  lng: number
  lat: number
  /** Metres above the ground level the hook adds. */
  height: number
  pitchDeg: number
  range: number
}

/** The pose for a parcel's [west, south, east, north] bounds. */
export function sitePose(
  [west, south, east, north]: readonly [number, number, number, number],
  { aspectRatio = 1, fovy = Math.PI / 3 }: { aspectRatio?: number; fovy?: number } = {},
): SitePose {
  const midLat = (south + north) / 2
  const dx = (east - west) * M_PER_DEG_LAT * Math.cos((midLat * Math.PI) / 180)
  const dy = (north - south) * M_PER_DEG_LAT
  const diagonal = Math.hypot(dx, dy)
  // Fit the bounding sphere in the smaller frustum dimension, including perspective at the near edge.
  const halfAngle = Math.atan(Math.tan(fovy / 2) * Math.min(1, aspectRatio) * FILL)
  const distance = diagonal / 2 / Math.sin(halfAngle)
  const pitch = (Math.abs(PITCH_DEG) * Math.PI) / 180
  const height = Math.max(MIN_HEIGHT_M, distance * Math.sin(pitch))
  const back = height / Math.tan(pitch)
  return { lng: (west + east) / 2, lat: midLat - back / M_PER_DEG_LAT, height, pitchDeg: PITCH_DEG, range: height / Math.sin(pitch) }
}
