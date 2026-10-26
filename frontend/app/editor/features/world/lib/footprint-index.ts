import { footprintBounds, overlaps, type Footprint } from './building-geometry'

const CELL = .001
const MAX_CELLS = 64

export class FootprintIndex {
  private cells = new Map<string, Footprint[]>()
  private large: Footprint[] = []

  constructor(private features: Footprint[]) {
    for (const f of features) {
      const keys = this.keys(f)
      if (!keys) { this.large.push(f); continue }
      for (const key of keys) {
        const bucket = this.cells.get(key)
        if (bucket) bucket.push(f)
        else this.cells.set(key, [f])
      }
    }
  }

  private keys(f: Footprint): string[] | null {
    const [west, south, east, north] = footprintBounds(f)
    const x0 = Math.floor(west / CELL), y0 = Math.floor(south / CELL)
    const x1 = Math.floor(east / CELL), y1 = Math.floor(north / CELL)
    // A stadium/campus may cross many cells; keep it in a bounded overflow list instead.
    if ((x1 - x0 + 1) * (y1 - y0 + 1) > MAX_CELLS) return null
    const keys: string[] = []
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) keys.push(`${x}/${y}`)
    return keys
  }

  overlaps(f: Footprint): boolean {
    const keys = this.keys(f)
    if (!keys) return this.features.some(t => overlaps(f, t))
    if (this.large.some(t => overlaps(f, t))) return true
    const seen = new Set<Footprint>()
    for (const key of keys) for (const t of this.cells.get(key) ?? []) {
      if (seen.has(t)) continue
      seen.add(t)
      if (overlaps(f, t)) return true
    }
    return false
  }
}
