import { parcelOutline } from './parcelOutline'

/** The searched location: a small filled dot with a white ring, in the outline's red. */
export const searchMarker = {
  color: parcelOutline.color,
  ring: '#ffffff',
  radius: 6,
  ringWidth: 2,
} as const

/** Marker content for providers that take HTML markers (Naver). */
export function searchMarkerHtml() {
  const size = (searchMarker.radius + searchMarker.ringWidth) * 2
  return `<div style="width:${size}px;height:${size}px;box-sizing:border-box;border-radius:50%;background:${searchMarker.color};border:${searchMarker.ringWidth}px solid ${searchMarker.ring};box-shadow:0 1px 3px rgb(0 0 0 / .35)"></div>`
}
