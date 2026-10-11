export type Pixel = readonly [number, number]
type Raster = { width: number; height: number; data: Uint8ClampedArray }

function area(ring: readonly Pixel[]) {
  return Math.abs(ring.reduce((sum, p, i) => {
    const q = ring[(i + 1) % ring.length]!
    return sum + p[0] * q[1] - q[0] * p[1]
  }, 0)) / 2
}

function contains(ring: readonly Pixel[], x: number, y: number) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i]!, b = ring[j]!
    if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside
  }
  return inside
}

function fitEdges(contour: Pixel[], source: readonly Pixel[], allowance: number): Pixel[] | null {
  const vertices = source.slice(0, -1)
  const lines: { a: Pixel; direction: Pixel }[] = []
  for (let i = 0; i < vertices.length; i++) {
    const a = vertices[i]!, b = vertices[(i + 1) % vertices.length]!
    const length = Math.hypot(b[0] - a[0], b[1] - a[1])
    if (length < 12) return null
    const dx = (b[0] - a[0]) / length, dy = (b[1] - a[1]) / length
    const points = contour.map(([x, y]) => [(x - a[0]) * dx + (y - a[1]) * dy, -(x - a[0]) * dy + (y - a[1]) * dx] as Pixel)
      .filter(([u, v]) => u > length * 0.15 && u < length * 0.85 && Math.abs(v) < allowance)
    if (points.length < 8) return null
    let best: Pixel[] = []
    const step = Math.max(1, Math.floor(points.length / 30))
    for (let j = 0; j < points.length; j += step) for (let k = j + step; k < points.length; k += step) {
      const p = points[j]!, q = points[k]!
      if (Math.abs(q[0] - p[0]) <= length * 0.3) continue
      const slope = (q[1] - p[1]) / (q[0] - p[0]), intercept = p[1] - slope * p[0]
      if (Math.abs(slope) > 0.2) continue
      const inliers = points.filter(([u, v]) => Math.abs(v - slope * u - intercept) < 1)
      if (inliers.length > best.length) best = inliers
    }
    if (best.length < points.length * 0.5 || best.length < 8) return null
    const uMean = best.reduce((sum, p) => sum + p[0], 0) / best.length
    const vMean = best.reduce((sum, p) => sum + p[1], 0) / best.length
    const slope = best.reduce((sum, p) => sum + (p[0] - uMean) * (p[1] - vMean), 0) / best.reduce((sum, p) => sum + (p[0] - uMean) ** 2, 0)
    const intercept = vMean - slope * uMean
    lines.push({ a: [a[0] - dy * intercept, a[1] + dx * intercept], direction: [dx - dy * slope, dy + dx * slope] })
  }
  const result: Pixel[] = []
  for (let i = 0; i < lines.length; i++) {
    const p = lines[(i + lines.length - 1) % lines.length]!, q = lines[i]!
    const cross = p.direction[0] * q.direction[1] - p.direction[1] * q.direction[0]
    if (Math.abs(cross) < 0.05) return null
    const t = ((q.a[0] - p.a[0]) * q.direction[1] - (q.a[1] - p.a[1]) * q.direction[0]) / cross
    const point: Pixel = [p.a[0] + t * p.direction[0], p.a[1] + t * p.direction[1]]
    if (Math.hypot(point[0] - vertices[i]![0], point[1] - vertices[i]![1]) > allowance) return null
    result.push(point)
  }
  result.push(result[0]!)
  return result
}

// This is a display contour only. The provider's raster cannot replace cadastral geometry used for design.
export function traceSelection({ width, height, data }: Raster, source: readonly Pixel[]): Pixel[] | null {
  const sourceArea = area(source)
  if (sourceArea < 200 || source.some(([x, y]) => x < 2 || y < 2 || x >= width - 2 || y >= height - 2)) return null
  const west = Math.floor(Math.min(...source.map(p => p[0]))), east = Math.ceil(Math.max(...source.map(p => p[0])))
  const north = Math.floor(Math.min(...source.map(p => p[1]))), south = Math.ceil(Math.max(...source.map(p => p[1])))
  const colors = new Map<number, { count: number; seed: number; distance: number }>()
  const cx = (west + east) / 2, cy = (north + south) / 2
  for (let y = north; y <= south; y += 2) for (let x = west; x <= east; x += 2) {
    if (!contains(source, x, y)) continue
    const index = y * width + x, offset = index * 4
    if (data[offset + 3]! < 240) continue
    const color = (data[offset]! << 16) | (data[offset + 1]! << 8) | data[offset + 2]!
    const distance = (x - cx) ** 2 + (y - cy) ** 2
    const entry = colors.get(color)
    if (!entry) colors.set(color, { count: 1, seed: index, distance })
    else { entry.count++; if (distance < entry.distance) { entry.seed = index; entry.distance = distance } }
  }
  const dominant = [...colors.entries()].sort((a, b) => b[1].count - a[1].count)[0]
  if (!dominant || dominant[1].count < sourceArea / 16) return null
  const [color, { seed }] = dominant
  const rgb = [color >> 16, (color >> 8) & 255, color & 255]
  const seen = new Uint8Array(width * height), mask = new Uint8Array(width * height)
  const queue = [seed]
  seen[seed] = 1
  let count = 0, overlap = 0
  for (let head = 0; head < queue.length; head++) {
    const index = queue[head]!, x = index % width, y = Math.floor(index / width), offset = index * 4
    if (data[offset + 3]! < 240 || rgb.some((v, c) => Math.abs(data[offset + c]! - v) > 12)) continue
    if (x === 0 || y === 0 || x === width - 1 || y === height - 1 || ++count > sourceArea * 1.5) return null
    mask[index] = 1
    if (contains(source, x, y)) overlap++
    for (const next of [index - 1, index + 1, index - width, index + width]) {
      if (!seen[next]) { seen[next] = 1; queue.push(next) }
    }
  }
  if (count < sourceArea * 0.6 || overlap < Math.min(count, sourceArea) * 0.7) return null

  const stride = width + 1
  const edges = new Map<number, number[]>()
  function edge(a: number, b: number) { const list = edges.get(a) ?? []; list.push(b); edges.set(a, list) }
  for (const index of queue) {
    if (!mask[index]) continue
    const x = index % width, y = Math.floor(index / width), a = y * stride + x
    if (!mask[index - width]) edge(a, a + 1)
    if (!mask[index + 1]) edge(a + 1, a + stride + 1)
    if (!mask[index + width]) edge(a + stride + 1, a + stride)
    if (!mask[index - 1]) edge(a + stride, a)
  }
  let outer: Pixel[] = []
  while (edges.size) {
    const start = edges.keys().next().value!
    const ring: Pixel[] = []
    let at = start
    do {
      ring.push([at % stride, Math.floor(at / stride)])
      const options = edges.get(at)
      if (!options?.length) return null
      const next = options.pop()!
      if (!options.length) edges.delete(at)
      at = next
    } while (at !== start)
    if (area(ring) > area(outer)) outer = ring
  }
  if (!outer.length) return null
  const allowance = Math.max(6, Math.sqrt(sourceArea) * 0.25)
  const result = fitEdges(outer, source, allowance)
  if (!result || area(result) < sourceArea * 0.6 || area(result) > sourceArea * 1.5) return null
  if (result.some(([x, y]) => x < west - allowance || x > east + allowance || y < north - allowance || y > south + allowance)) return null
  return result
}
