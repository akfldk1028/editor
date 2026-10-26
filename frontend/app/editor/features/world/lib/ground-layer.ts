/* eslint-disable @typescript-eslint/no-explicit-any */
// Cesium gives each DataSource its own OrderedGroundPrimitiveCollection; an
// entity zIndex does not order it against entities in another DataSource.
const groundOrder = new WeakMap<object, Map<any, number>>()
function orderGroundSources(viewer: any) {
  const collection = viewer.dataSources
  if (!collection.contains || !collection.lowerToBottom) return
  const sources = [...(groundOrder.get(viewer) ?? [])]
    .filter(([source]) => collection.contains(source))
    .sort((a, b) => a[1] - b[1])
  // Keep non-ground sources (site highlights/layout) above this background,
  // preserving their relative order and every bounded batch's identity.
  for (let i = sources.length - 1; i >= 0; i--) collection.lowerToBottom(sources[i]![0])
}

/** Cesium re-batches a data source when its entities change; keep that rebuild independent of total map size. */
export class GroundLayer {
  private sources: any[] = []
  private owners = new Map<string, any>()
  private items = new Map<string, any>()
  private cells = new Map<string, Set<string>>()
  private references = new Map<string, Set<string>>()
  private surfaceIds = new Set<string>()
  private surfaceMode = false
  private roadIds = new Set<string>()
  private roadMode = false
  private visible = true
  private suspended = 0
  private sequence = 0

  constructor(private viewer: any, private C: any, readonly name: string, private capacity = 128) {
    Object.defineProperty(this.entities, 'values', { get: () => [...this.items.values()] })
  }

  get show() { return this.visible }
  set show(value: boolean) { this.visible = value; for (const source of this.sources) source.show = value }

  /** Imagery owns only background parcel/cover fills, never roads or boundaries. */
  get surfaceImagery() { return this.surfaceMode }
  set surfaceImagery(enabled: boolean) {
    if (enabled === this.surfaceMode) return
    this.surfaceMode = enabled
    this.setChannelImagery(this.surfaceIds, enabled)
  }
  get roadImagery() { return this.roadMode }
  set roadImagery(enabled: boolean) {
    if (enabled === this.roadMode) return
    this.roadMode = enabled
    this.setChannelImagery(this.roadIds, enabled)
  }
  private setChannelImagery(ids: Set<string>, enabled: boolean) {
    this.entities.suspendEvents()
    try {
      for (const id of ids) {
        const entity = this.items.get(id)
        if (!entity) continue
        if (enabled) {
          this.owners.get(id)?.entities.removeById(id)
          this.owners.delete(id)
        } else {
          this.items.delete(id)
          this.add(entity)
        }
      }
    } finally { this.entities.resumeEvents() }
    this.pruneEmpty()
  }

  /** Register shared geometry even when the renderer skips an already drawn id. */
  forCell(key: string) {
    const claim = (entity: any) => {
      if (!entity) return entity
      let ids = this.cells.get(key)
      if (!ids) this.cells.set(key, ids = new Set())
      ids.add(entity.id)
      let cells = this.references.get(entity.id)
      if (!cells) this.references.set(entity.id, cells = new Set())
      cells.add(key)
      return entity
    }
    return { entities: {
      getById: (id: string) => claim(this.entities.getById(id)),
      add: (entity: any) => claim(this.entities.add(entity)),
      addSurface: (entity: any) => claim(this.entities.addSurface(entity)),
      addRoad: (entity: any) => claim(this.entities.addRoad(entity)),
      suspendEvents: this.entities.suspendEvents,
      resumeEvents: this.entities.resumeEvents,
    } }
  }

  retireCell(key: string) {
    this.entities.suspendEvents()
    for (const id of this.cells.get(key) ?? []) {
      const cells = this.references.get(id)
      cells?.delete(key)
      if (!cells?.size) {
        this.references.delete(id)
        this.entities.removeById(id)
      }
    }
    this.cells.delete(key)
    this.entities.resumeEvents()
    this.pruneEmpty()
  }

  pruneEmpty() {
    if (this.suspended) return
    this.sources = this.sources.filter(source => {
      if (source.entities.values.length) return true
      groundOrder.get(this.viewer)?.delete(source)
      this.viewer.dataSources.remove(source, true)
      return false
    })
  }

  private add(entity: any) {
    if (this.items.has(entity.id)) throw new Error(`Duplicate ground entity: ${entity.id}`)
    // Local context is loaded only near the camera. Keep it cached when zooming
    // out, but avoid displaying a sharp-edged island of local detail at city scale.
    for (const kind of ['polygon', 'polyline']) {
      if (entity[kind] && !entity[kind].distanceDisplayCondition) {
        entity[kind].distanceDisplayCondition = new this.C.DistanceDisplayCondition(0, 4000)
      }
    }
    const priority = typeof entity.polygon?.zIndex === 'number' ? entity.polygon.zIndex : 0
    let orders = groundOrder.get(this.viewer)
    if (!orders) groundOrder.set(this.viewer, orders = new Map())
    let source = this.owners.get(entity.id)
    if (!source || source.entities.values.length >= this.capacity) {
      source = this.sources.find(s => orders!.get(s) === priority && s.entities.values.length < this.capacity)
      if (!source) {
        source = new this.C.CustomDataSource(`${this.name}/${this.sequence++}`)
        source.show = this.visible
        if (this.suspended) source.entities.suspendEvents()
        this.sources.push(source)
        orders.set(source, priority)
        const added = source
        void Promise.resolve(this.viewer.dataSources.add(added)).then(() => {
          if (this.viewer.isDestroyed?.()) return
          if (!this.sources.includes(added)) this.viewer.dataSources.remove(added, true)
          else orderGroundSources(this.viewer)
        })
      }
    }
    const added = source.entities.add(entity)
    this.owners.set(entity.id, source)
    this.items.set(entity.id, added)
    return added
  }

  readonly entities = {
    add: (entity: any) => this.add(entity),
    addSurface: (entity: any) => {
      if (this.items.has(entity.id)) throw new Error(`Duplicate ground entity: ${entity.id}`)
      this.surfaceIds.add(entity.id)
      if (!this.surfaceMode) return this.add(entity)
      // Retain geometry and cell ownership without allocating a Cesium primitive.
      this.items.set(entity.id, entity)
      return entity
    },
    addRoad: (entity: any) => {
      if (this.items.has(entity.id)) throw new Error(`Duplicate ground entity: ${entity.id}`)
      this.roadIds.add(entity.id)
      if (!this.roadMode) return this.add(entity)
      this.items.set(entity.id, entity)
      return entity
    },
    getById: (id: string) => this.items.get(id),
    removeById: (id: string) => {
      if (!this.items.delete(id)) return false
      const source = this.owners.get(id)
      this.owners.delete(id)
      this.surfaceIds.delete(id)
      this.roadIds.delete(id)
      return source ? source.entities.removeById(id) : true
    },
    removeAll: () => {
      for (const source of this.sources) {
        groundOrder.get(this.viewer)?.delete(source)
        this.viewer.dataSources.remove(source, true)
      }
      this.sources = []; this.owners.clear(); this.items.clear()
      this.cells.clear(); this.references.clear()
      this.surfaceIds.clear(); this.roadIds.clear()
    },
    suspendEvents: () => { if (this.suspended++ === 0) for (const s of this.sources) s.entities.suspendEvents() },
    resumeEvents: () => { if (--this.suspended === 0) for (const s of this.sources) s.entities.resumeEvents() },
    get values(): any[] { return [] },
  }
}
