/** Shared by browser display/camera sampling and the offline building baker. */
export const TERRAIN_HEIGHT_CONTRACT = 'resolved-ancestor-grid-v1' as const
export type TerrainGridKey = { level: number; x: number; y: number }
export type ResolvedTerrainGrid = {
  heights: Float32Array
  /** -1 is confirmed all-ancestor NoData, represented at ellipsoid zero; never measured. */
  sourceLevels: Int8Array
  archiveSha256: string
  contract: typeof TERRAIN_HEIGHT_CONTRACT
}

/** Finite contributors retain their bilinear weights; zero-weight neighbours supply no evidence. */
export function supportedGridHeight(grid: Float32Array, x: number, y: number, size = 33): number | undefined {
  const last = size - 1
  const fx = Math.max(0, Math.min(last, x)), fy = Math.max(0, Math.min(last, y))
  const col = Math.min(last - 1, Math.floor(fx)), row = Math.min(last - 1, Math.floor(fy))
  const u = fx - col, v = fy - row
  const indices = [row * size + col, row * size + col + 1, (row + 1) * size + col, (row + 1) * size + col + 1]
  const weights = [(1-u)*(1-v), u*(1-v), (1-u)*v, u*v]
  let weight = 0, height = 0
  for (let i = 0; i < 4; i++) {
    const value = grid[indices[i]!]!, contribution = weights[i]!
    if (contribution > 0 && Number.isFinite(value)) { weight += contribution; height += contribution * value }
  }
  return weight > 0 ? height / weight : undefined
}

export function createTerrainHeightContract(
  raw: (key: TerrainGridKey) => Promise<Float32Array | null>,
  policy: { archiveSha256: string; minLevel: number; maxLevel: number; size?: number; keep?: number },
) {
  const size = policy.size ?? 33, last = size - 1, keep = policy.keep ?? 512
  if (!/^[a-f0-9]{64}$/.test(policy.archiveSha256) || !Number.isInteger(size) || size < 2
    || !Number.isInteger(policy.minLevel) || !Number.isInteger(policy.maxLevel)
    || policy.minLevel < 0 || policy.maxLevel > 20 || policy.minLevel > policy.maxLevel || keep < 1) throw new Error('Invalid terrain contract policy')
  const cache = new Map<string, Promise<ResolvedTerrainGrid>>()
  const pointSources = new Map<string, Float32Array | null>()
  const pointPending = new Map<string, Promise<Float32Array | null>>()
  const identity = `${policy.archiveSha256}/${TERRAIN_HEIGHT_CONTRACT}`
  const resolve = (key: TerrainGridKey): Promise<ResolvedTerrainGrid> => {
    const { level, x, y } = key
    if (![level, x, y].every(Number.isInteger) || level < policy.minLevel || level > policy.maxLevel
      || x < 0 || y < 0 || x >= 2 ** (level + 1) || y >= 2 ** level) return Promise.reject(new Error('Outside terrain contract grid'))
    const id = `${identity}/${level}/${x}/${y}`
    const prior = cache.get(id)
    if (prior) { cache.delete(id); cache.set(id, prior); return prior }
    const result = (async () => {
      const heights = new Float32Array(size * size), sourceLevels = new Int8Array(size * size).fill(-1)
      let unresolved = heights.length
      for (let source = level; source >= policy.minLevel && unresolved; source--) {
        const scale = 2 ** (level - source), ax = Math.floor(x / scale), ay = Math.floor(y / scale)
        // An exception must escape: a failed read is never confirmed NoData.
        const grid = await raw({ level: source, x: ax, y: ay })
        if (!grid) continue
        if (grid.length !== heights.length) throw new Error('Invalid raw terrain grid size')
        for (let row = 0; row < size; row++) for (let col = 0; col < size; col++) {
          const index = row * size + col
          if (sourceLevels[index] !== -1) continue
          const value = supportedGridHeight(grid, ((x - ax * scale) + col / last) / scale * last,
            ((y - ay * scale) + row / last) / scale * last, size)
          if (value !== undefined) { heights[index] = value; sourceLevels[index] = source; unresolved-- }
        }
      }
      return { heights, sourceLevels, archiveSha256: policy.archiveSha256, contract: TERRAIN_HEIGHT_CONTRACT }
    })()
    cache.set(id, result)
    void result.catch(() => { if (cache.get(id) === result) cache.delete(id) })
    while (cache.size > keep) cache.delete(cache.keys().next().value!)
    return result
  }
  const sample = (grid: ResolvedTerrainGrid, x: number, y: number) => {
      if (grid.archiveSha256 !== policy.archiveSha256 || grid.contract !== TERRAIN_HEIGHT_CONTRACT) throw new Error('Mismatched terrain grid')
      const height = supportedGridHeight(grid.heights, x, y, size)
      if (height === undefined) throw new Error('Unresolved terrain grid')
      return height
  }
  return { identity, resolve, sample, size, minLevel: policy.minLevel, maxLevel: policy.maxLevel,
    async samplePosition(lon: number, lat: number) {
      if (!Number.isFinite(lon) || !Number.isFinite(lat) || lon < -180 || lon > 180 || lat < -90 || lat > 90) throw new Error('Outside terrain coordinates')
      const level = policy.maxLevel, width = 180 / 2 ** level
      const x = Math.min(2 ** (level + 1) - 1, Math.floor((lon + 180) / width))
      const y = Math.min(2 ** level - 1, Math.floor((90 - lat) / width))
      const gx = Math.max(0, Math.min(last, (lon + 180 - x * width) / width * last))
      const gy = Math.max(0, Math.min(last, (90 - lat - y * width) / width * last))
      const col = Math.min(last - 1, Math.floor(gx)), row = Math.min(last - 1, Math.floor(gy)), u = gx - col, v = gy - row
      const indices = [row*size+col, row*size+col+1, (row+1)*size+col, (row+1)*size+col+1]
      const weights = [(1-u)*(1-v),u*(1-v),(1-u)*v,u*v]
      const cached = cache.get(`${identity}/${level}/${x}/${y}`)
      if (cached) {
        const grid = await resolve({ level, x, y })
        const sourceLevels = [...new Set(indices.filter((_, i) => weights[i]! > 0).map(index => grid.sourceLevels[index]!))].sort((a,b) => a-b)
        return { height: sample(grid, gx, gy), sourceLevels, ellipsoidZero: sourceLevels.includes(-1),
          archiveSha256: policy.archiveSha256, contract: TERRAIN_HEIGHT_CONTRACT }
      }
      const heights = new Float32Array(4), levels = new Int8Array(4).fill(-1)
      const columns = [col, col+1, col, col+1], rows = [row, row, row+1, row+1]
      let unresolved = weights.filter(weight => weight > 0).length
      for (let source = level; source >= policy.minLevel && unresolved; source--) {
        const scale = 2 ** (level-source), ax = Math.floor(x/scale), ay = Math.floor(y/scale)
        const key = `${source}/${ax}/${ay}`
        let grid: Float32Array | null
        if (pointSources.has(key)) {
          grid=pointSources.get(key)!; pointSources.delete(key); pointSources.set(key,grid)
        } else {
          let pending=pointPending.get(key)
          if (!pending) {
            pending=Promise.resolve().then(() => raw({ level: source, x: ax, y: ay })).then(value => {
              if (value && value.length !== size*size) throw new Error('Invalid raw terrain grid size')
              pointSources.set(key,value)
              while (pointSources.size > keep) pointSources.delete(pointSources.keys().next().value!)
              return value
            }).finally(() => { if (pointPending.get(key)===pending) pointPending.delete(key) })
            pointPending.set(key,pending)
          }
          grid=await pending
        }
        if (!grid) continue
        if (grid.length !== size*size) throw new Error('Invalid raw terrain grid size')
        for (let i=0; i<4; i++) {
          if (weights[i]! <= 0 || levels[i] !== -1) continue
          const value = supportedGridHeight(grid, ((x-ax*scale)+columns[i]!/last)/scale*last,
            ((y-ay*scale)+rows[i]!/last)/scale*last, size)
          // Float32 assignment matches resolve(), including rounding before the final interpolation.
          if (value !== undefined) { heights[i]=value; levels[i]=source; unresolved-- }
        }
      }
      let height=0, weight=0
      for (let i=0; i<4; i++) if (weights[i]! > 0 && Number.isFinite(heights[i])) {
        weight+=weights[i]!; height+=weights[i]!*heights[i]!
      }
      const sourceLevels=[...new Set(Array.from(levels).filter((_,i)=>weights[i]!>0))].sort((a,b)=>a-b)
      return { height: height/weight, sourceLevels, ellipsoidZero: sourceLevels.includes(-1),
        archiveSha256: policy.archiveSha256, contract: TERRAIN_HEIGHT_CONTRACT }
    },
  }
}
