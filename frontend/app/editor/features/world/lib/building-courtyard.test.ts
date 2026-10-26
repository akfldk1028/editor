import { expect, test } from 'bun:test'
import fixture from './gosan-courtyard.fixture.json'
import { decodeBuildings, type Footprint } from './building-geometry'
import { bakeMesh, coarseFootprint, frame, meshFootprintBounds } from './prebuilt-mesh'
import { prepareBuildingMesh } from './building-mesh'

async function sample() {
  class Pbf { constructor(_: unknown) {} }
  class VectorTile { layers = { buildings: { length: 50, feature: (i: number) => i === 49
    ? { type: 3, extent: fixture.extent, properties: fixture.properties, loadGeometry: () => fixture.rings }
    : { type: 0, properties: {} } } } }
  return (await decodeBuildings(new Uint8Array(), fixture.tile, Pbf, VectorTile))[0]!
}
function baked(f: Footprint) {
  const bytes = bakeMesh([f], frame(127.10525, 37.73282), false), view = new DataView(bytes.buffer)
  const offset = 28 + view.getUint32(12, true) + view.getUint32(20, true), size = view.getUint32(offset + 12, true)
  const doc = JSON.parse(new TextDecoder().decode(bytes.slice(offset + 20, offset + 20 + size)))
  const start = offset + 28 + size
  return { positions: new Float32Array(bytes.buffer, start + doc.bufferViews[0].byteOffset, doc.accessors[0].count * 3),
    normals: new Float32Array(bytes.buffer, start + doc.bufferViews[1].byteOffset, doc.accessors[1].count * 3) }
}
function contains(p: number[], a: number[], b: number[], c: number[]) {
  const cross = (u: number[], v: number[]) => (v[0]! - u[0]!) * (p[1]! - u[1]!) - (v[1]! - u[1]!) * (p[0]! - u[0]!)
  const signs = [cross(a, b), cross(b, c), cross(c, a)]
  return signs.every(v => v >= -1e-6) || signs.every(v => v <= 1e-6)
}
test('actual Gosan MVT preserves its 23.61 percent courtyard and source identity', async () => {
  const f = await sample()
  expect(f.key).toBe('16/55906/25340/49')
  expect(f.holes).toHaveLength(1)
  expect(f.ring[0]).toEqual([127.1052248775959, 37.732924168023196])
  const area = (r: number[][]) => Math.abs(r.reduce((s,p,i) => { const q=r[(i+1)%r.length]!;return s+(p[0]!-r[0]![0]!)*(q[1]!-r[0]![1]!)-(q[0]!-r[0]![0]!)*(p[1]!-r[0]![1]!) },0))
  expect(area(f.holes![0]!) / area(f.ring)).toBeCloseTo(0.2361232, 5)
})
test('actual Gosan courtyard stays open in both prepared and baked roofs for either winding', async () => {
  const f = await sample(), origin = frame(127.10525, 37.73282)
  const point = origin.point(127.10525660133098,37.73282075535137,f.z!+f.h)
  for (const reverse of [false,true]) {
    const source = { ...f, ring: reverse ? [...f.ring].reverse() : f.ring,
      holes: f.holes?.map(r => reverse ? [...r].reverse() : r) }
    const mesh = prepareBuildingMesh(source)!, bakedMesh = baked(source)
    const local = new Float64Array(mesh.positions.length)
    for(let i=0;i<local.length;i+=3) {
      const v=[0,1,2].map(j=>mesh.positions[i+j]!-origin.transform[12+j]!)
      local[i]=v.reduce((s,x,j)=>s+x*origin.transform[j]!,0)
      local[i+1]=v.reduce((s,x,j)=>s+x*origin.transform[8+j]!,0)
      local[i+2]=-v.reduce((s,x,j)=>s+x*origin.transform[4+j]!,0)
    }
    for(const positions of [local,bakedMesh.positions]) {
      let roofTriangles=0,covered=0
      for(let i=0;i<positions.length;i+=9) {
        if(Math.max(...[1,4,7].map(j=>Math.abs(positions[i+j]!-point[1]!)))>.1)continue
        roofTriangles++
        const vertices=[0,3,6].map(j=>[positions[i+j]!,positions[i+j+2]!])
        if(contains([point[0]!,point[2]!],vertices[0]!,vertices[1]!,vertices[2]!))covered++
      }
      expect(roofTriangles).toBeGreaterThan(0)
      expect(covered).toBe(0)
    }
  }
})
test('coarse box retains a rotated slender footprint without filling its axis-aligned envelope', () => {
  const angle=.65, scale=1e-5, coslat=Math.cos(37*Math.PI/180)
  const ring=[[0,0],[100,0],[100,5],[0,5],[0,0]].map(([x,y])=>[127+(x!*Math.cos(angle)-y!*Math.sin(angle))*scale/coslat,37+(x!*Math.sin(angle)+y!*Math.cos(angle))*scale])
  const f:Footprint={key:'slender',pnu:'',h:10,z:50,s:'m',ring}
  const coarse=coarseFootprint(f)
  const area=(r:number[][])=>Math.abs(r.reduce((s,p,i)=>{const q=r[(i+1)%r.length]!;return s+(p[0]!-127)*(q[1]!-37)-(q[0]!-127)*(p[1]!-37)},0))
  expect(area(coarse.ring)/area(ring)).toBeLessThan(1.001)
  const metres=(p:number[])=>[(p[0]!-127)*111320*coslat,(p[1]!-37)*111320]
  const corners=coarse.ring.map(metres)
  for(const p of ring.map(metres)) expect(contains(p,corners[0]!,corners[1]!,corners[2]!)||contains(p,corners[0]!,corners[2]!,corners[3]!)).toBe(true)
  expect(f.ring).toBe(ring)
})

test('inner walls face the courtyard void in runtime and baked meshes regardless of ring windings', () => {
  const outer=[[127.105,37.7326],[127.1055,37.7326],[127.1055,37.733],[127.105,37.733],[127.105,37.7326]]
  const hole=[[127.1051,37.7327],[127.1054,37.7327],[127.1054,37.7329],[127.1051,37.7329],[127.1051,37.7327]]
  const origin=frame(127.10525,37.73282),center=origin.point(127.10525,37.7328,0)
  for(const reverseOuter of [false,true]) for(const reverseHole of [false,true]) {
    const f:Footprint={key:'courtyard',pnu:'',h:12,z:50,s:'m',ring:reverseOuter?[...outer].reverse():outer,holes:[reverseHole?[...hole].reverse():hole]}
    const runtime=prepareBuildingMesh(f)!, bakedMesh=baked(f)
    for(const [mesh,ecef] of [[runtime,true],[bakedMesh,false]] as const) {
      for(let i=mesh.positions.length-24*3;i<mesh.positions.length;i+=18) {
        let p=Array.from(mesh.positions.slice(i,i+3)), n=Array.from(mesh.normals.slice(i,i+3))
        if(ecef) {
          const v=p.map((x,j)=>x-origin.transform[12+j]!)
          p=[v.reduce((s,x,j)=>s+x*origin.transform[j]!,0),0,-v.reduce((s,x,j)=>s+x*origin.transform[4+j]!,0)]
          n=[n.reduce((s,x,j)=>s+x*origin.transform[j]!,0),0,-n.reduce((s,x,j)=>s+x*origin.transform[4+j]!,0)]
        }
        expect(n[0]!*(center[0]!-p[0]!)+n[2]!*(center[2]!-p[2]!)).toBeGreaterThan(0)
      }
    }
  }
})

test('mesh culling bounds include rotated coarse corners extending outside original bounds', () => {
  const f:Footprint={key:'triangle',pnu:'',s:'m',z:50,h:10,
    ring:[[127,37],[127.004,37.001],[127.001,37.002],[127,37]]}
  const coarse=coarseFootprint(f), bounds=meshFootprintBounds(f)
  expect(coarse.ring.some(p=>p[0]!<127-1e-10||p[0]!>127.004+1e-10||p[1]!<37-1e-10||p[1]!>37.002+1e-10)).toBe(true)
  for(const p of [...f.ring,...coarse.ring]) {
    expect(p[0]!).toBeGreaterThanOrEqual(bounds[0]);expect(p[0]!).toBeLessThanOrEqual(bounds[2])
    expect(p[1]!).toBeGreaterThanOrEqual(bounds[1]);expect(p[1]!).toBeLessThanOrEqual(bounds[3])
  }
})

test('MVT multipolygon interiors attach only to their preceding exterior', async () => {
  const ring=(x:number,size:number,reverse=false)=>{
    const r=[{x,y:0},{x:x+size,y:0},{x:x+size,y:size},{x,y:size},{x,y:0}]
    return reverse?r.reverse():r
  }
  const rings=[ring(0,100),ring(20,20,true),ring(200,100),ring(220,20,true)]
  class Pbf { constructor(_:unknown){} }
  class VectorTile { layers={buildings:{length:1,feature:()=>({type:3,extent:4096,properties:{h:10},loadGeometry:()=>rings})}} }
  const features=await decodeBuildings(new Uint8Array(),fixture.tile,Pbf,VectorTile)
  expect(features).toHaveLength(2)
  expect(features.map(f=>f.holes?.length)).toEqual([1,1])
  expect(features[0]!.holes![0]![0]![0]).toBeLessThan(features[1]!.ring[0]![0]!)
  expect(features[1]!.holes![0]![0]![0]).toBeGreaterThan(features[1]!.ring[0]![0]!)
})
