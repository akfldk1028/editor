import { expect, test } from 'bun:test'
import { createGroundStages, drawContextGround, drawGroundIncrementally } from './context-masses'
import { GroundLayer } from './ground-layer'

const outer = [[127, 37], [127.01, 37], [127.01, 37.01], [127, 37.01], [127, 37]]
const hole = [[127.002, 37.002], [127.003, 37.002], [127.003, 37.003], [127.002, 37.002]]
function fixture() {
  const layer = () => ({ entities: { values: [] as any[], suspendEvents() {}, resumeEvents() {},
    removeById(id: string) { this.values = this.values.filter(e => e.id !== id) },
    getById(id: string) { return this.values.find(e => e.id === id) }, add(e: any) { this.values.push(e) } } })
  const targets = { blocks: layer(), cover: layer() }
  class Hierarchy { constructor(public positions: any, public holes: any[] = []) {} }
  const C = { PolygonHierarchy: Hierarchy, PolylineDashMaterialProperty: class {}, ClassificationType: { TERRAIN: 0 },
    DistanceDisplayCondition: class { constructor(public near: number, public far: number) {} },
    Color: { fromCssColorString: (s: string) => s }, Cartesian3: { fromDegreesArray: (a: number[]) => a } }
  return { targets, C }
}

test('clipped parcel and cover fragments retain their full geometry, including holes', () => {
  const { targets, C } = fixture()
  const left = [[127,37],[127.005,37],[127.005,37.01],[127,37.01],[127,37]]
  const right = [[127,37],[127.01,37],[127.01,37.01],[127,37.01],[127,37]]
  const draw = (layer: string, poly: number[][][]) => drawContextGround(targets,C,{status:'ok',features:{type:'FeatureCollection',features:[{
    properties:{id:'shared-pnu',layer,ground:'lot',cover:'green'},geometry:{type:'Polygon',coordinates:poly},
  }]}},'terrain')
  for (const layer of ['ground','cover']) {
    expect(draw(layer,[left])).toBe(1)
    expect(draw(layer,[right])).toBe(1)
    expect(draw(layer,[right,hole])).toBe(1)
    expect(draw(layer,[left])).toBe(0)
  }
  expect(targets.blocks.entities.values).toHaveLength(3)
  expect(targets.cover.entities.values).toHaveLength(3)
})
test('carriageways are drawn over paving and polygon holes survive', () => {
  const { targets, C } = fixture()
  const reply: any = { status: 'ok', features: { features: [
    { properties: { id: 'road', layer: 'ground', ground: 'paved' }, geometry: { type: 'Polygon', coordinates: [outer, hole] } },
    { properties: { id: 'road', layer: 'carriageway', width_m: 6.5 }, geometry: { type: 'Polygon', coordinates: [outer] } },
  ] } }
  expect(drawContextGround(targets, C, reply, 'terrain')).toBe(2)
  const [paved, road] = targets.blocks.entities.values
  expect(paved.polygon.hierarchy.holes).toHaveLength(1)
  expect(paved.polygon.material).toBe('#e2e1dc')
  expect(road.polygon.zIndex).toBeGreaterThan(paved.polygon.zIndex)
  expect(road.polygon.classificationType).toBe(C.ClassificationType.TERRAIN)
  expect(paved.polygon.classificationType).toBe(C.ClassificationType.TERRAIN)
  expect(paved.polyline).toBeUndefined()
  expect(drawContextGround(targets, C, reply, 'terrain')).toBe(0)
})

test('only evidenced original boundary segments are drawn, never clipping cut edges', () => {
  const { targets, C } = fixture()
  const trueEdge = [[127,37],[127,37.01]]
  const reply: any = { status:'ok',features:{features:[{properties:{id:'pnu',layer:'ground',ground:'lot',
    parcel_boundary:{type:'MultiLineString',coordinates:[trueEdge]}},geometry:{type:'Polygon',coordinates:[outer]}}]} }
  expect(drawContextGround(targets,C,reply,'terrain')).toBe(1)
  const polygon=targets.blocks.entities.values.find(e=>e.polygon)
  const lines=targets.blocks.entities.values.filter(e=>e.polyline)
  expect(polygon.polygon.hierarchy.positions).toEqual(outer.flat())
  expect(polygon.polyline).toBeUndefined()
  expect(lines).toHaveLength(1)
  expect(lines[0].polyline.positions).toEqual(trueEdge.flat())
  expect(lines[0].polyline.classificationType).toBe(C.ClassificationType.TERRAIN)
  drawContextGround(targets,C,reply,'terrain')
  expect(targets.blocks.entities.values).toHaveLength(2)
  reply.features.features[0].properties.parcel_boundary_id = 'pnu'
  reply.features.features[0].properties.id = 'pnu:green'
  drawContextGround(targets,C,reply,'terrain')
  expect(targets.blocks.entities.values.filter(e=>e.polyline)).toHaveLength(1)
})

test('boundary-only refresh preserves fills and roads and shares hole edges across clipped owners', async () => {
  const { targets: plain, C }=fixture()
  class Source {
    entities=fixture().targets.blocks.entities
    constructor(public name:string) {
      const add=this.entities.add.bind(this.entities)
      this.entities.add=(entity:any)=>{add(entity);return entity}
    }
  }
  const layer=new GroundLayer({dataSources:{add:(s:any)=>s,remove(){}}},{...C,CustomDataSource:Source},'ground')
  const initial:any={status:'ok',features:{features:[{properties:{id:'road',layer:'carriageway'},geometry:{type:'Polygon',coordinates:[outer]}}]}}
  drawContextGround({blocks:layer.forCell('a'),cover:plain.cover},C,initial,'terrain')
  const road=layer.entities.values[0]
  const reply:any={status:'ok',features:{features:[{properties:{id:'pnu',layer:'ground',ground:'lot',
    parcel_boundary:{type:'GeometryCollection',geometries:[{type:'MultiLineString',coordinates:[hole]},{type:'LineString',coordinates:[]}]}},
    geometry:{type:'Polygon',coordinates:[outer]}}]}}
  const draw=(key:string)=>drawGroundIncrementally({blocks:layer.forCell(key),cover:plain.cover},C,reply,'terrain',()=>true,()=>{},
    {state:{begin(){throw new Error('boundary refresh entered road lifecycle')}} as any,cellKey:key,detail:'full'},true)
  await draw('a');await draw('b')
  expect(layer.entities.values.filter(e=>e.polygon)).toEqual([road])
  expect(layer.entities.values.filter(e=>e.polyline)).toHaveLength(1)
  expect(layer.entities.values.find(e=>e.polyline).polyline.positions).toEqual(hole.flat())
  layer.retireCell('a')
  expect(layer.entities.values).toHaveLength(1)
  layer.retireCell('b')
  expect(layer.entities.values).toHaveLength(0)
})

test('incremental full response replaces actual road entities and preserves overlapping owners', async () => {
  const { targets, C } = fixture()
  const state = createGroundStages(targets, C, () => 'terrain')
  const feature = (id: string, width: number) => ({ properties: { id, layer: 'carriageway', width_m: width },
    geometry: { type: 'Polygon', coordinates: [outer.map(([x, y]) => [x! + width / 1000, y])] } })
  const draw = (cellKey: string, detail: 'roads' | 'full', features: any[], record?: any) =>
    drawGroundIncrementally(targets, C, { status: 'ok', features: { type: 'FeatureCollection', features }, record },
      'terrain', () => true, () => {}, { state, cellKey, detail })
  await draw('a', 'roads', [feature('shared', 4), feature('old', 4)])
  await draw('b', 'roads', [feature('shared', 4)])
  await draw('a', 'full', [feature('shared', 8)])
  expect(targets.blocks.entities.values).toHaveLength(1)
  const updated = targets.blocks.entities.values[0]
  expect(updated.name).toContain('8 m')
  expect(updated.polygon.hierarchy.positions[0]).toBe(127.008)
  await draw('c', 'roads', [feature('shared', 5)])
  expect(targets.blocks.entities.values[0]).toBe(updated)
  await draw('a', 'full', [])
  expect(targets.blocks.entities.values).toHaveLength(1)
  await draw('b', 'full', [])
  await draw('c', 'full', [])
  expect(targets.blocks.entities.values).toHaveLength(0)
})

test('full ground with failed road evidence retains installed road entities', async () => {
  const { targets, C } = fixture()
  const state = createGroundStages(targets, C, () => 'terrain')
  await drawGroundIncrementally(targets, C, { status: 'ok', features: { type: 'FeatureCollection', features: [
    { properties: { id: 'road', layer: 'carriageway' }, geometry: { type: 'Polygon', coordinates: [outer] } },
  ] } }, 'terrain', () => true, () => {}, { state, cellKey: 'a', detail: 'roads' })
  await drawGroundIncrementally(targets, C, { status: 'ok', record: { roads: { owner: 'SiteContext site_roads' } },
    features: { type: 'FeatureCollection', features: [] } }, 'terrain', () => true, () => {}, { state, cellKey: 'a', detail: 'full' })
  expect(targets.blocks.entities.values).toHaveLength(1)
})

test('incremental drawing stops after disposal instead of draining cached features', async () => {
  const { targets, C } = fixture()
  let live = true
  const add = targets.blocks.entities.add.bind(targets.blocks.entities)
  targets.blocks.entities.add = entity => {
    add(entity)
    if (targets.blocks.entities.values.length === 32) live = false
  }
  const features = Array.from({ length: 200 }, (_, id) => ({ properties: { id, layer: 'carriageway' },
    geometry: { type: 'Polygon', coordinates: [outer] } }))
  await drawGroundIncrementally(targets, C, { status: 'ok', features: { type: 'FeatureCollection', features } },
    'terrain', () => live, () => {})
  expect(targets.blocks.entities.values).toHaveLength(32)
})

test('revision-backed full roads replace the preview geometry', async () => {
  const { targets, C } = fixture()
  const state = createGroundStages(targets, C, () => 'terrain')
  const feature = (width: number) => ({ properties: { id: 'road', layer: 'carriageway', width_m: width },
    geometry: { type: 'Polygon', coordinates: [outer] } })
  for (const [detail, width] of [['roads', 4], ['full', 8]] as const) {
    await drawGroundIncrementally(targets, C, { status: 'ok', record: { roads: { revision: 'installed-source', completeness: 'installed-sheets-only' } },
      features: { type: 'FeatureCollection', features: [feature(width)] } }, 'terrain', () => true, () => {}, { state, cellKey: 'a', detail })
  }
  expect(targets.blocks.entities.values).toHaveLength(1)
  expect(targets.blocks.entities.values[0].name).toContain('8 m')
})

test('partial full roads cannot acquire ordinary ownership and erase another cell on eviction', async () => {
  const { targets: plain, C } = fixture()
  const viewer = { dataSources: { add: (source: any) => source, remove() {} } }
  const cesium = { ...C, CustomDataSource: class {
    entities = fixture().targets.blocks.entities
  } }
  // The real Cesium EntityCollection.add returns the entity being registered.
  const original = cesium.CustomDataSource
  class Source extends original {
    constructor() {
      super()
      const add = this.entities.add.bind(this.entities)
      this.entities.add = (entity: any) => { add(entity); return entity }
    }
  }
  const layer = new GroundLayer(viewer, { ...cesium, CustomDataSource: Source }, 'ground')
  const state = createGroundStages({ blocks: layer, cover: plain.cover }, C, () => 'terrain')
  const feature = { properties: { id: 'shared', layer: 'carriageway' }, geometry: { type: 'Polygon', coordinates: [outer] } }
  const draw = (cellKey: string, detail: 'roads' | 'full', gaps?: string[]) => drawGroundIncrementally(
    { blocks: layer.forCell(cellKey), cover: plain.cover }, C,
    { status: 'ok', gaps, features: { type: 'FeatureCollection', features: [feature] } },
    'terrain', () => true, () => {}, { state, cellKey, detail })
  await draw('a', 'roads')
  await draw('b', 'roads')
  await draw('a', 'full', ['carriageways: 1 centreline without lanes left out'])
  state.retire('a')
  layer.retireCell('a')
  expect(layer.entities.getById('carriageway-shared-0')).toBeDefined()
  state.retire('b')
  layer.retireCell('b')
  expect(layer.entities.values).toHaveLength(0)
})

test('incremental chunks release events before yielding and also after rendering failures', async () => {
  const { targets, C } = fixture()
  let depth = 0, flushes = 0
  targets.blocks.entities.suspendEvents = () => { depth++ }
  targets.blocks.entities.resumeEvents = () => { if (--depth === 0) flushes++ }
  const features = Array.from({ length: 65 }, (_, id) => ({ properties: { id, layer: 'carriageway' },
    geometry: { type: 'Polygon', coordinates: [outer] } }))
  const draw = () => drawGroundIncrementally(targets, C, { status: 'ok', features: { type: 'FeatureCollection', features } },
    'terrain', () => true, () => {})
  await draw()
  expect(flushes).toBe(3)
  expect(depth).toBe(0)
  // A malformed source/renderer failure must not leave future cells suspended.
  targets.blocks.entities.values = []
  targets.blocks.entities.add = () => { throw new Error('render failed') }
  await expect(draw()).rejects.toThrow('render failed')
  expect(depth).toBe(0)
})
