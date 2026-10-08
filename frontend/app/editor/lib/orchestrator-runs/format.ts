/** Formatting every agent's lines share. Pure. */
export const fmt = (value: number, digits: number) => value.toLocaleString('ko-KR', { maximumFractionDigits: digits })

/** "20250925" → "2025-09-25"; other shapes stay. */
export const isoDate = (value: string) => (/^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}` : value)

/** A passage under a link: enough to recognise the clause; the whole text lives in the law artifact. */
const EXCERPT = 220
export const excerpt = (text: string | null) => (text ? (text.length > EXCERPT ? `${text.slice(0, EXCERPT)}…` : text) : null)
