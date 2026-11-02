import { readFile, writeFile } from 'node:fs/promises'
import { PMTiles } from 'pmtiles'
import Pbf from 'pbf'
import { VectorTile } from '@mapbox/vector-tile'
import { openLocalArchive } from './local-building-archive'

const [archivePath, baselinePath, progressPath, output] = process.argv.slice(2)
const baseline = JSON.parse(await readFile(baselinePath!, 'utf8')) as {key:string}[]
const filled = new Set<string>(JSON.parse(await readFile(progressPath!, 'utf8')).newlyFilledKeys)
const grouped = new Map<string, Map<number,string>>()
for (const {key} of baseline) {
  const parts=key.split('/'),index=Number(parts.pop()),tile=parts.join('/')
  const group=grouped.get(tile) ?? new Map<number,string>(); group.set(index,key);grouped.set(tile,group)
}
const normalize=(p:unknown)=>{const c=String(p??'').slice(0,2);return c==='42'?'51':c==='45'?'52':c}
const provinces: Record<string,any>={}
const keys: Record<string,string>={}
const centres: [string,string,number,number][]=[['11','Seoul',126.978,37.5665],['26','Busan',129.0756,35.1796],['27','Daegu',128.6014,35.8714],['28','Incheon',126.7052,37.4563],['29','Gwangju',126.8526,35.1595],['30','Daejeon',127.3845,36.3504],['31','Ulsan',129.3114,35.5384],['36','Sejong',127.289,36.480],['41','Gyeonggi',127.0286,37.2636],['43','Chungbuk',127.489,36.642],['44','Chungnam',126.672,36.659],['46','Jeonnam',126.462,34.816],['47','Gyeongbuk',128.729,36.568],['48','Gyeongnam',128.681,35.228],['50','Jeju',126.5312,33.4996],['51','Gangwon',127.729,37.881],['52','Jeonbuk',127.148,35.824]]
for(const [code,name] of centres)provinces[code]={code,name,baseline:0,filled:0,remaining:0}
const file=await openLocalArchive(archivePath!),archive=new PMTiles(file)
const sourceExamples:any[]=[]
try {
  for (const [tile,rows] of grouped) {
    const [z,x,y]=tile.split('/').map(Number),bytes=await archive.getZxy(z!,x!,y!)
    if(!bytes)throw Error(`Missing source tile ${tile}`)
    const layer=new VectorTile(new Pbf(new Uint8Array(bytes.data))).layers.buildings!
    for(const [index,key] of rows) {
      const code=normalize(layer.feature(index).properties.p);keys[key]=code
      const row=provinces[code]??(provinces[code]={code,name:'unknown',baseline:0,filled:0,remaining:0})
      row.baseline++;row.filled+=Number(filled.has(key));row.remaining+=Number(!filled.has(key))
    }
  }
  for(const [code,name,lon,lat] of centres) {
    const tx=Math.floor((lon+180)/360*65536),ty=Math.floor((1-Math.asinh(Math.tan(lat*Math.PI/180))/Math.PI)/2*65536)
    let found=false
    for(let dx=-1;dx<=1&&!found;dx++)for(let dy=-1;dy<=1&&!found;dy++) {
      const x=tx+dx,y=ty+dy,bytes=await archive.getZxy(16,x,y);if(!bytes)continue
      const layer=new VectorTile(new Pbf(new Uint8Array(bytes.data))).layers.buildings
      if(!layer)continue
      for(let i=0;i<layer.length;i++) {
        const feature=layer.feature(i),observed=normalize(feature.properties.p)
        if(observed!==code&&!(['29','46'].includes(code)&&observed==='12'))continue
        const geometry=feature.toGeoJSON(x,y,16).geometry as any
        const point=geometry.type==='Polygon'?geometry.coordinates[0][0]:geometry.coordinates[0][0][0]
        sourceExamples.push({code,name,sourceProvinceCode:observed,key:`16/${x}/${y}/${i}`,point});found=true;break
      }
    }
    if(!found)sourceExamples.push({code,name,error:'No matching building in nine city-centre source tiles'})
  }
} finally {await file.close()}
const result={unit:'unique source tile feature keys; baseline is not a census of all nationwide buildings',sourceArchive:archivePath,provinces:Object.values(provinces),keyProvinces:keys,sourceExamples}
await writeFile(output!,JSON.stringify(result));console.log(JSON.stringify({provinces:result.provinces,sourceExamples}))
