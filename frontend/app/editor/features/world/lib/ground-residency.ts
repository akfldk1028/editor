/** Retain recent views without letting a long trip accumulate every ground cell. */
export class GroundResidency {
  private cells = new Set<string>()
  constructor(private capacity: number) {}
  clear() { this.cells.clear() }
  visit(keys: Iterable<string>): string[] {
    const wanted = new Set(keys)
    for (const key of wanted) { this.cells.delete(key); this.cells.add(key) }
    const retired: string[] = []
    for (const key of this.cells) {
      if (this.cells.size <= this.capacity) break
      if (wanted.has(key)) continue
      this.cells.delete(key)
      retired.push(key)
    }
    return retired
  }
}
