import {request} from './api';

export type Position=[number,number];
export type Polygon=Position[][];
export type ParcelGeometry={type:'Polygon';coordinates:Polygon}|{type:'MultiPolygon';coordinates:Polygon[]};
export interface ParcelResult {geometry:ParcelGeometry;pnu?:string|null;address?:string|null}
export type ParcelQuery={pnu:string}|{x:number;y:number};

function isPolygon(value:unknown):value is Polygon {
  return Array.isArray(value)&&value.length>0&&value.every(ring=>Array.isArray(ring)&&ring.length>=4&&
    ring.every(point=>Array.isArray(point)&&point.length===2&&point.every(n=>typeof n==='number'&&Number.isFinite(n))&&
      Math.abs(point[0])<=180&&Math.abs(point[1])<=90)&&
    ring[0][0]===ring[ring.length-1][0]&&ring[0][1]===ring[ring.length-1][1]);
}
function isGeometry(value:unknown):value is ParcelGeometry {
  if(!value||typeof value!=='object')return false;
  const geometry=value as Record<string,unknown>;
  return geometry.type==='Polygon'?isPolygon(geometry.coordinates):geometry.type==='MultiPolygon'&&
    Array.isArray(geometry.coordinates)&&geometry.coordinates.length>0&&geometry.coordinates.every(isPolygon);
}
export async function lookupParcel(query:ParcelQuery,signal:AbortSignal):Promise<ParcelResult> {
  const response:unknown=await request('pnu' in query?'parcel-geometry':'reverse',signal,query);
  if(!response||typeof response!=='object')throw new Error('필지 응답 형식이 올바르지 않습니다.');
  const value=response as Record<string,unknown>;
  if(value.success===false)throw new Error(typeof value.error==='string'&&value.error.includes('not configured')?
    '필지 조회 서비스 설정이 필요합니다.':'필지 경계를 조회하지 못했습니다.');
  if(value.success!==true||!isGeometry(value.geometry)||
    (value.pnu!==undefined&&value.pnu!==null&&(typeof value.pnu!=='string'||!/^\d{19}$/.test(value.pnu)))||
    (value.address!==undefined&&value.address!==null&&typeof value.address!=='string'))
    throw new Error('필지 응답 형식이 올바르지 않습니다.');
  return {geometry:value.geometry,pnu:value.pnu as string|null|undefined,address:value.address as string|null|undefined};
}
