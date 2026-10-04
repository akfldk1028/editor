import type {ParcelGeometry} from './parcel-api';

export default function ParcelPreview({geometry}:{geometry:ParcelGeometry}) {
  const polygons=geometry.type==='Polygon'?[geometry.coordinates]:geometry.coordinates;
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  for(const polygon of polygons)for(const ring of polygon)for(const [x,y] of ring){
    minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);
  }
  const scale=280/Math.max(maxX-minX,maxY-minY,1e-9);
  const offsetX=(320-(maxX-minX)*scale)/2;
  const offsetY=(320-(maxY-minY)*scale)/2;
  return <figure className="parcel-preview">
    <svg viewBox="0 0 320 320" role="img" aria-label="필지 경계 미리보기">
      {polygons.map((polygon,i)=><path key={i} fillRule="evenodd" d={polygon.map(ring=>ring.map(([x,y],j)=>
        `${j===0?'M':'L'}${(offsetX+(x-minX)*scale).toFixed(3)},${(offsetY+(maxY-y)*scale).toFixed(3)}`).join(' ')+' Z').join(' ')}/>)}
    </svg>
    <figcaption>북쪽이 위입니다. 경위도 기반 미리보기이며 측량 치수·면적을 나타내지 않습니다.</figcaption>
  </figure>;
}
