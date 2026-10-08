/** A 지번 chip over a selected parcel; styled by `.site-map-chip` in site-map.css (shell tokens). */
export function lotChipElement(text: string): HTMLDivElement {
  const chip = document.createElement('div')
  chip.className = 'site-map-chip'
  chip.textContent = text
  return chip
}

/** The same chip as HTML, for providers that take marker HTML (Naver). */
export function lotChipHtml(text: string): string {
  return lotChipElement(text).outerHTML
}
