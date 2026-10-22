/**
 * Where the 3D camera stands to show a parcel: high and far enough that the whole parcel and a ring of its
 * neighbours fill the view, never the fixed 520 m pose that left a 2,500 ㎡ parcel a speck on the screen.
 * Pure; the hook turns it into a Cesium flight.
 */
const M_PER_DEG_LAT = 111_320
const PITCH_DEG = -42
/** The parcel's diagonal takes about this share of the view's height; the rest is its surroundings. */
const FILL = 0.45
const MIN_HEIGHT_M = 90
const MAX_HEIGHT_M = 700

export interface SitePose {
  /** Camera position: the parcel centre moved south, so a north-facing oblique view looks at it. */
  lng: number
  lat: number
  /** Metres above the ground level the hook adds. */
  height: number
  pitchDeg: number
}

/** The pose for a parcel's [west, south, east, north] bounds. */
export function sitePose([west, south, east, north]: readonly [number, number, number, number]): SitePose {
  const midLat = (south + north) / 2
  const dx = (east - west) * M_PER_DEG_LAT * Math.cos((midLat * Math.PI) / 180)
  const dy = (north - south) * M_PER_DEG_LAT
  const diagonal = Math.hypot(dx, dy)
  // A 60° vertical field of view sees about 1.15 × the distance at the target; distance = diagonal / FILL / 1.15.
  const distance = diagonal / FILL / 1.15
  const pitch = (Math.abs(PITCH_DEG) * Math.PI) / 180
  const height = Math.min(MAX_HEIGHT_M, Math.max(MIN_HEIGHT_M, distance * Math.sin(pitch)))
  const back = height / Math.tan(pitch)
  return { lng: (west + east) / 2, lat: midLat - back / M_PER_DEG_LAT, height, pitchDeg: PITCH_DEG }
}
