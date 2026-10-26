type Detail = 'roads' | 'full'
type Road = { properties?: Record<string, any>; geometry?: any }
type Contribution = { feature: Road; detail: Detail; revision: number }

export const roadKey = (feature: Road): string => `carriageway-${feature.properties?.id ?? JSON.stringify(feature.geometry)}`

export function nextGroundRequest(queue: readonly { cellKey: string; detail: Detail }[],
  active: Iterable<{ detail: Detail }>, roadsReady: ReadonlySet<string>, allowFull = true, allowRoads = true): number {
  const full = allowFull ? queue.findIndex(c => c.detail === 'full' && roadsReady.has(c.cellKey)) : -1
  const roads = allowRoads ? queue.findIndex(c => c.detail === 'roads') : -1
  // Keep preview capacity while roads are waiting, then let the caller's bounded
  // pool fill its spare slots with full cells instead of serializing the tail.
  if (full >= 0 && (roads < 0 || ![...active].some(c => c.detail === 'full'))) return full
  return roads
}

/** One road can belong to several overlapping cells; retiring one preview must not erase another cell's coverage. */
export class GroundStages {
  private revision = 0
  private cells = new Map<string, { detail: Detail; revision: number; ids: Set<string> }>()
  private owners = new Map<string, Map<string, Contribution>>()
  private shown = new Map<string, Road>()

  constructor(private replace: (previous: Road | undefined, next: Road | undefined, id: string) => void) {}

  clear() { this.cells.clear(); this.owners.clear(); this.shown.clear() }

  retire(cellKey: string) {
    const cell = this.cells.get(cellKey)
    this.cells.delete(cellKey)
    for (const id of cell?.ids ?? []) {
      this.owners.get(id)?.delete(cellKey)
      this.reconcile(id)
    }
  }

  private reconcile(id: string) {
    let winner: Contribution | undefined
    for (const candidate of this.owners.get(id)?.values() ?? []) {
      if (!winner || (candidate.detail === 'full' && winner.detail === 'roads')
        || (candidate.detail === winner.detail && candidate.revision > winner.revision)) winner = candidate
    }
    const previous = this.shown.get(id), next = winner?.feature
    if (previous === next) return
    this.replace(previous, next, id)
    if (next) this.shown.set(id, next)
    else { this.shown.delete(id); this.owners.delete(id) }
  }

  begin(cellKey: string, detail: Detail) {
    const previous = this.cells.get(cellKey)
    if (detail === 'roads' && previous?.detail === 'full') return null
    const cell = { detail, revision: ++this.revision, ids: previous?.ids ?? new Set<string>() }
    this.cells.set(cellKey, cell)
    const seen = new Set<string>()
    const current = () => this.cells.get(cellKey) === cell
    let retiring: SetIterator<string> | undefined
    return {
      current,
      apply: (feature: Road) => {
        if (!current()) return
        const id = roadKey(feature)
        seen.add(id)
        cell.ids.add(id)
        let owners = this.owners.get(id)
        if (!owners) this.owners.set(id, owners = new Map())
        owners.set(cellKey, { feature, detail, revision: cell.revision })
        this.reconcile(id)
      },
      finish: (limit = Infinity): boolean => {
        if (!current()) return true
        retiring ??= cell.ids.values()
        for (let n = 0; n < limit; n++) {
          const next = retiring.next()
          if (next.done) { cell.ids = seen; return true }
          if (!seen.has(next.value)) {
            this.owners.get(next.value)?.delete(cellKey)
            this.reconcile(next.value)
          }
        }
        return false
      },
    }
  }
}
