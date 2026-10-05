type Ring = [number, number, ...number[]][];
type Polygon = Ring[];

function polygons(value: unknown): Polygon[] {
  if (!value || typeof value !== 'object') return [];
  const item = value as Record<string, unknown>;
  if (item.type === 'FeatureCollection' && Array.isArray(item.features)) return item.features.flatMap(polygons);
  if (item.type === 'Feature') return polygons(item.geometry);
  const candidates = item.type === 'Polygon' ? [item.coordinates]
    : item.type === 'MultiPolygon' && Array.isArray(item.coordinates) ? item.coordinates : [];
  return candidates.filter((polygon): polygon is Polygon => Array.isArray(polygon) && polygon.length > 0 &&
    polygon.every(ring => Array.isArray(ring) && ring.length >= 4 && ring.every(point =>
      Array.isArray(point) && point.length >= 2 && Number.isFinite(point[0]) && Number.isFinite(point[1]))));
}

export function DesignFootprint({geometry, context}: {geometry: unknown; context: unknown}) {
  const shapes = polygons(geometry);
  if (!shapes.length) return <p>표시할 수 있는 저장된 면 형상이 없습니다.</p>;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const polygon of shapes) for (const ring of polygon) for (const [x, y] of ring) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  const width = maxX - minX, height = maxY - minY;
  if (!Number.isFinite(width) || !Number.isFinite(height) || Math.max(width, height) <= 0)
    return <p>저장된 형상의 좌표 범위를 확인할 수 없습니다.</p>;
  const scale = 360 / Math.max(width, height);
  const left = (400 - width * scale) / 2, top = (400 - height * scale) / 2;
  return <figure className="saved-design-footprint">
    <svg viewBox="0 0 400 400" role="img" aria-label="저장된 설계 평면 형상">
      {shapes.map((polygon, index) => <path key={index} fillRule="evenodd" d={polygon.map(ring =>
        ring.map(([x, y], point) => `${point ? 'L' : 'M'}${(left + (x - minX) * scale).toFixed(3)},${(top + (maxY - y) * scale).toFixed(3)}`).join(' ') + ' Z').join(' ')} />)}
    </svg>
    <figcaption>저장된 면 형상의 X/Y 평면 투영입니다. 층수와 높이는 이 그림에서 추정하지 않습니다.</figcaption>
    <p>X: {minX} ~ {maxX} · Y: {minY} ~ {maxY}</p>
    <details open><summary>원본 좌표 정보</summary><pre>{context == null ? '좌표계·단위 정보가 제공되지 않았습니다.' : JSON.stringify(context, null, 2)}</pre></details>
  </figure>;
}
