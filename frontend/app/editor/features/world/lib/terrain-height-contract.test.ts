import { expect, test } from 'bun:test'
import { createTerrainHeightContract, supportedGridHeight } from './terrain-height-contract'
import type { TerrainGridKey } from './terrain-height-contract'

const policy = { archiveSha256: 'a'.repeat(64), minLevel: 0, maxLevel: 2, size: 3 }
const key = { level: 2, x: 0, y: 0 }

test('finite bilinear weights cannot borrow zero-weight support at an empty exact vertex', () => {
  const grid = new Float32Array(9).fill(80); grid[0] = NaN
  expect(supportedGridHeight(grid, 0, 0, 3)).toBeUndefined()
  expect(supportedGridHeight(grid, 1e-13, 0, 3)).toBe(80)
  expect(supportedGridHeight(grid, 0.5, 0.5, 3)).toBe(80)
})

test('present NoData vertices resolve explicit ancestors and display/sample share the resolved surface', async () => {
  const fine = new Float32Array(9).fill(80); fine[0] = NaN
  const contract = createTerrainHeightContract(async k => k.level === 2 ? fine : new Float32Array(9).fill(20), policy)
  const grid = await contract.resolve(key)
  expect(grid.heights[0]).toBe(20); expect(grid.sourceLevels[0]).toBe(1)
  expect(grid.sourceLevels[1]).toBe(2)
  expect(contract.sample(grid, 0.5, 0.5)).toBe(65)
  expect(supportedGridHeight(fine, 0.5, 0.5, 3)).toBe(80)
})

test('missing and all-NoData ancestors produce explicit zero only after every read succeeds', async () => {
  const calls: number[] = []
  const contract = createTerrainHeightContract(async k => { calls.push(k.level); return k.level === 1 ? new Float32Array(9).fill(NaN) : null }, policy)
  const grid = await contract.resolve(key)
  expect(calls).toEqual([2,1,0]); expect(grid.heights.every(x => x === 0)).toBe(true)
  expect(grid.sourceLevels.every(x => x === -1)).toBe(true)
})

test('failed read is not cached as zero and retry can recover', async () => {
  let fail = true
  const contract = createTerrainHeightContract(async () => { if (fail) throw Error('network'); return new Float32Array(9).fill(70) }, policy)
  await expect(contract.resolve(key)).rejects.toThrow('network')
  fail = false
  expect((await contract.resolve(key)).heights[0]).toBe(70)
})

test('camera order and cache eviction cannot alter resolved vertices', async () => {
  const raw = async (k: { level: number }) => k.level === 2 ? null : new Float32Array([1,2,3,4,5,6,7,8,9])
  const contract = createTerrainHeightContract(raw, { ...policy, keep: 1 })
  const first = await contract.resolve(key)
  await contract.resolve({ level: 1, x: 1, y: 0 })
  expect(Array.from((await contract.resolve(key)).heights)).toEqual(Array.from(first.heights))
  const other = createTerrainHeightContract(raw, { ...policy, archiveSha256: 'b'.repeat(64) })
  expect(other.identity).not.toBe(contract.identity)
  expect(() => other.sample(first, 0, 0)).toThrow('Mismatched')
})

async function fullGridSample(contract: ReturnType<typeof createTerrainHeightContract>, lon: number, lat: number) {
  const level=contract.maxLevel,width=180/2**level,size=contract.size,last=size-1
  const x=Math.min(2**(level+1)-1,Math.floor((lon+180)/width)),y=Math.min(2**level-1,Math.floor((90-lat)/width))
  const grid=await contract.resolve({level,x,y})
  const gx=Math.max(0,Math.min(last,(lon+180-x*width)/width*last)),gy=Math.max(0,Math.min(last,(90-lat-y*width)/width*last))
  const col=Math.min(last-1,Math.floor(gx)),row=Math.min(last-1,Math.floor(gy)),u=gx-col,v=gy-row
  const indices=[row*size+col,row*size+col+1,(row+1)*size+col,(row+1)*size+col+1],weights=[(1-u)*(1-v),u*(1-v),(1-u)*v,u*v]
  const sourceLevels=[...new Set(indices.filter((_,i)=>weights[i]!>0).map(i=>grid.sourceLevels[i]!))].sort((a,b)=>a-b)
  return {height:contract.sample(grid,gx,gy),sourceLevels,ellipsoidZero:sourceLevels.includes(-1),archiveSha256:grid.archiveSha256,contract:grid.contract}
}

test('point sampling reads at most four required vertices instead of resolving all 1089', async () => {
  let reads=0
  const values=new Float32Array(1089).fill(93.123456)
  const grid=new Proxy(values,{get(target,key){if(typeof key==='string'&&/^\d+$/.test(key))reads++;return Reflect.get(target,key,target)}})
  const c=createTerrainHeightContract(async()=>grid,{archiveSha256:'a'.repeat(64),minLevel:11,maxLevel:20})
  expect((await c.samplePosition(127.1025,37.734)).height).toBe(values[0]!)
  expect(reads).toBeLessThanOrEqual(16)
})

test('seeded points, exact boundaries and NoData equal full Float32 grid heights and provenance bit for bit', async () => {
  let seed=123456789
  const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/2**32}
  const points=Array.from({length:2500},()=>[random()*360-180,random()*180-90])
  points.push([-180,90],[180,-90],[0,0],[-180,-90],[180,90])
  for(let i=0;i<100;i++)points.push([-180+i*180/256,90-i*180/256],[-180+i*180/256+180/256/32,90-i*180/256-180/256/32])
  const raw=async(k:TerrainGridKey)=>{
    if((k.x+k.y+k.level)%7===0)return null
    const h=new Float32Array(1089)
    for(let i=0;i<h.length;i++){
      const v=(Math.imul(k.x+17,1664525)^Math.imul(k.y+29,1013904223)^Math.imul(i+1,214013)^k.level)>>>0
      h[i]=(v%11<5 || (k.x===0&&k.y===0))?NaN:(v%1000000)/127-500
    }
    return h
  }
  const p={archiveSha256:'a'.repeat(64),minLevel:3,maxLevel:8,keep:1}
  const fast=createTerrainHeightContract(raw,p),gold=createTerrainHeightContract(raw,p)
  for(const [lon,lat] of points){
    const expected=await fullGridSample(gold,lon!,lat!),actual=await fast.samplePosition(lon!,lat!)
    expect(Object.is(actual.height,expected.height)).toBe(true)
    expect(actual).toEqual(expected)
  }
})

test('point sampling preserves retry, zero-weight exclusions, all-NoData and existing display cache reuse', async () => {
  let fail=true,calls=0
  const c=createTerrainHeightContract(async()=>{calls++;if(fail)throw Error('read failed');return new Float32Array(9).fill(NaN)},policy)
  await expect(c.samplePosition(-180,90)).rejects.toThrow('read failed')
  fail=false
  expect(await c.samplePosition(-180,90)).toEqual({height:0,sourceLevels:[-1],ellipsoidZero:true,archiveSha256:policy.archiveSha256,contract:'resolved-ancestor-grid-v1'})
  await c.resolve(key);const before=calls
  expect((await c.samplePosition(-180,90)).height).toBe(0);expect(calls).toBe(before)
  const fine=new Float32Array(9).fill(80);fine[0]=NaN
  const edge=createTerrainHeightContract(async k=>k.level===2?fine:new Float32Array(9).fill(20),policy)
  expect((await edge.samplePosition(-180,90)).sourceLevels).toEqual([1])
  expect(await edge.samplePosition(-180+1e-10,90)).toEqual(await fullGridSample(edge,-180+1e-10,90))
})

test('point samples share bounded raw reads and retry malformed grids without retaining failures', async () => {
  let calls=0,bad=true
  const c=createTerrainHeightContract(async()=>{calls++;return new Float32Array(bad?1:9).fill(70)},policy)
  await expect(c.samplePosition(-170,80)).rejects.toThrow('grid size')
  bad=false
  const results=await Promise.all(Array.from({length:20},()=>c.samplePosition(-170,80)))
  expect(results.every(r=>r.height===70)).toBe(true)
  expect(calls).toBe(2)
})

test('settled LRU pressure never evicts pending point reads', async () => {
  let calls=0
  const releases: Array<() => void>=[]
  const c=createTerrainHeightContract(async()=>{
    calls++
    await new Promise<void>(resolve=>releases.push(resolve))
    return new Float32Array(9).fill(70)
  },{...policy,keep:1})
  const first=c.samplePosition(-170,80),second=c.samplePosition(-100,80)
  await Promise.resolve();await Promise.resolve()
  const duplicate=c.samplePosition(-170,80)
  await Promise.resolve()
  expect(calls).toBe(2)
  releases.forEach(release=>release())
  expect((await Promise.all([first,second,duplicate])).map(value=>value.height)).toEqual([70,70,70])
})
