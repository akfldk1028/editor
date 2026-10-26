import { expect, test } from 'bun:test'
import { GroundLayer } from './ground-layer'

test('ground draw order is global across layers, late batches and mixed road/parcel arrivals', async () => {
  const sources: any[] = []
  class Source {
    show = true
    constructor(public name: string) {}
    entities = { values: [] as any[], add(e: any) { this.values.push(e); return e },
      removeById(id: string) { const i=this.values.findIndex(e=>e.id===id); if(i<0)return false; this.values.splice(i,1);return true },
      suspendEvents() {}, resumeEvents() {} }
  }
  const viewer = { dataSources: { add(s: any) { sources.push(s); return Promise.resolve(s) },
    remove(s: any) { const i=sources.indexOf(s); if(i>=0)sources.splice(i,1) },
    contains(s: any) { return sources.includes(s) },
    lowerToBottom(s: any) { const i=sources.indexOf(s); sources.splice(i,1);sources.unshift(s) } } }
  class DistanceDisplayCondition { constructor(public near: number, public far: number) {} }
  const C={ CustomDataSource: Source, DistanceDisplayCondition }
  const ground=new GroundLayer(viewer,C,'ground',2), cover=new GroundLayer(viewer,C,'cover',2)
  const layout=new Source('layout'); viewer.dataSources.add(layout)
  ground.entities.add({id:'road',polygon:{zIndex:2}})
  cover.entities.add({id:'green',polygon:{zIndex:1}})
  ground.entities.add({id:'parcel',polygon:{zIndex:0}})
  ground.entities.add({id:'parcel2',polygon:{zIndex:0}})
  ground.entities.add({id:'parcel3',polygon:{zIndex:0}})
  await Promise.resolve()
  const orders=sources.filter(s=>s!==layout).flatMap(s=>s.entities.values.map((e:any)=>e.polygon.zIndex))
  expect(orders).toEqual([0,0,0,1,2])
  expect(sources.at(-1)).toBe(layout)
  expect(sources.every(s=>new Set(s.entities.values.map((e:any)=>e.polygon?.zIndex)).size<=1)).toBe(true)
  ground.entities.removeAll(); cover.entities.removeAll()
  expect(sources).toEqual([layout])
})

function setup(deferred = false) {
  const sources: any[] = []
  const viewer = { dataSources: { add: (s: any) => deferred ? Promise.resolve().then(() => sources.push(s)) : sources.push(s),
    remove: (s: any) => { const index = sources.indexOf(s); if (index >= 0) sources.splice(index, 1) } } }
  class Source {
    show = true
    constructor(public name: string) {}
    entities = { values: [] as any[], add(e: any) { this.values.push(e); return e },
      removeById(id: string) { const i = this.values.findIndex(e => e.id === id); if (i < 0) return false; this.values.splice(i, 1); return true },
      suspendEvents() {}, resumeEvents() {} }
  }
  class DistanceDisplayCondition { constructor(public near: number, public far: number) {} }
  return { sources, layer: new GroundLayer(viewer, { CustomDataSource: Source, DistanceDisplayCondition }, 'ground', 2) }
}

test('local ground polygons and road lines share a distance limit without discarding cached entities', () => {
  const { layer } = setup()
  const cell = layer.forCell('local')
  cell.entities.add({ id: 'parcel', polygon: {} })
  cell.entities.add({ id: 'road', polyline: {} })
  for (const [id, graphic] of [['parcel', 'polygon'], ['road', 'polyline']]) {
    const entity = cell.entities.getById(id)
    expect(entity[graphic].distanceDisplayCondition).toEqual({ near: 0, far: 4000 })
    for (let i = 0; i < 3; i++) expect(cell.entities.getById(id)).toBe(entity)
  }
  expect(layer.entities.values).toHaveLength(2)
})

test('ground batches stay bounded and a replacement changes only its owning batch', () => {
  const { layer, sources } = setup()
  for (let i = 0; i < 5; i++) layer.entities.add({ id: String(i), value: 0 })
  expect(sources.map(s => s.entities.values.length)).toEqual([2, 2, 1])
  const untouched = sources[0].entities.values.slice()
  layer.entities.removeById('2')
  layer.entities.add({ id: '2', value: 1 })
  expect(sources[0].entities.values).toEqual(untouched)
  expect(layer.entities.getById('2').value).toBe(1)
  expect(sources.every(s => s.entities.values.length <= 2)).toBe(true)
  expect(layer.entities.values).toHaveLength(5)
  layer.show = false
  layer.entities.add({ id: '5' }); layer.entities.add({ id: '6' })
  expect(sources.every(s => !s.show)).toBe(true)
  layer.entities.removeAll()
  expect(sources).toHaveLength(0)
  expect(layer.entities.values).toHaveLength(0)
})

test('clearing before Cesium registers a source cannot leave an orphan batch', async () => {
  const { layer, sources } = setup(true)
  layer.entities.add({ id: 'late' })
  layer.entities.removeAll()
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(sources).toHaveLength(0)
})

test('retiring cells releases only unshared geometry and destroys empty batches', () => {
  const { layer, sources } = setup()
  const a = layer.forCell('a'), b = layer.forCell('b')
  a.entities.add({ id: 'shared' })
  a.entities.add({ id: 'only-a' })
  expect(b.entities.getById('shared')).toBeDefined()
  b.entities.add({ id: 'only-b' })
  layer.retireCell('a')
  expect(layer.entities.values.map(e => e.id)).toEqual(['shared', 'only-b'])
  layer.retireCell('b')
  expect(layer.entities.values).toHaveLength(0)
  expect(sources).toHaveLength(0)
  layer.forCell('a').entities.add({ id: 'shared' })
  expect(layer.entities.values).toHaveLength(1)
})

