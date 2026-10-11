import { expect, test } from 'bun:test'
import type { LngLat } from '../engine/types'
import { resolveDisplayHit } from './displayHit'
import { createDisplaySelection } from './displaySelection'
import { cadastralTileSource, captureCadastralRaster } from './naverRaster'
import { containsPoint } from './parcelOutline'

const source: LngLat[] = [[17,18],[57,18],[57,58],[17,58],[17,18]]
test('click in the shifted visible strip resolves inside the original parcel, without changing geometry', () => {
  const displayed: LngLat[] = source.map(([x,y])=>[x+5,y])
  const before=JSON.stringify(source)
  const result=resolveDisplayHit([60,40],[{source,displayed}])
  expect(containsPoint({type:'Polygon',coordinates:[source]},result)).toBe(true)
  expect(resolveDisplayHit([70,40],[{source,displayed}])).toEqual([70,40])
  expect(JSON.stringify(source)).toBe(before)
})

test('only current-zoom Naver cadastral tiles are accepted', () => {
  const base='https://nrbe.map.naver.net/styles/basic/version/20/100/200.png'
  expect(cadastralTileSource(base+'?mt=bg.ol.sw.lp',20)).not.toBeNull()
  expect(cadastralTileSource(base+'?mt=bg.ol.sw',20)).toBeNull()
  expect(cadastralTileSource(base+'?mt=bg.ol.sw.lp',19)).toBeNull()
  expect(cadastralTileSource(base.replace('nrbe.map.naver.net','example.org')+'?mt=lp',20)).toBeNull()
})

function raster(edge: number): ImageData {
  const data=new Uint8ClampedArray(80*80*4)
  for(let y=0;y<80;y++)for(let x=0;x<80;x++)data.set(x===edge||x===60||y===20||y===60?[140,140,120,255]:[250,250,160,255],(y*80+x)*4)
  return {width:80,height:80,data,colorSpace:'srgb'} as ImageData
}
test('same-zoom new tiles revalidate the contour, failed capture clears cached corrections', () => {
  let current: {raster:ImageData;sourceId:string}|null={raster:raster(20),sourceId:'version-a'}
  const selection=createDisplaySelection(()=>current)
  const projection={toPixel:(p:LngLat)=>p,toCoordinate:(p:LngLat)=>p}
  selection.capture({} as HTMLElement,20)
  expect(Math.min(...selection.ring(source,20,projection).map(p=>p[0]))).toBe(21)
  current={raster:raster(23),sourceId:'version-a'}
  selection.capture({} as HTMLElement,20)
  expect(Math.min(...selection.ring(source,20,projection).map(p=>p[0]))).toBe(24)
  current=null
  selection.capture({} as HTMLElement,20)
  expect(selection.ring(source,20,projection)).toBe(source)
})

test('visible incomplete or non-cadastral tiles invalidate capture rather than being filtered out', () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'document')
  const box = {left:0,top:0,right:80,bottom:80,width:80,height:80}
  const src='https://nrbe.map.naver.net/styles/basic/v1/20/1/2.png?mt=bg.lp'
  const tile = {src,currentSrc:src,complete:true,naturalWidth:256,getBoundingClientRect:()=>box}
  let images = [tile, {...tile,complete:false,naturalWidth:0}]
  const element={getBoundingClientRect:()=>box,querySelectorAll:()=>images} as unknown as HTMLElement
  Object.defineProperty(globalThis,'document',{configurable:true,value:{createElement:()=>({getContext:()=>({drawImage(){},getImageData:()=>raster(20)})})}})
  try {
    expect(captureCadastralRaster(element,20)).toBeNull()
    images=[tile,{...tile,currentSrc:src.replace('bg.lp','bg')}]
    expect(captureCadastralRaster(element,20)).toBeNull()
    images=[tile]
    expect(captureCadastralRaster(element,20)?.sourceId).toContain('mt=bg.lp')
  } finally {
    if(original)Object.defineProperty(globalThis,'document',original)
    else Reflect.deleteProperty(globalThis,'document')
  }
})
