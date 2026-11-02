import { mkdir, readFile, open } from 'node:fs/promises'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'
import type { Footprint } from '../features/world/lib/building-geometry'

export function groupBuildingRegions<T extends { z: number; x: number; y: number }>(regions: T[]) {
  const groups = new Map<string, T[]>()
  for (const region of regions) {
    if (region.z !== 14 || !Number.isInteger(region.x) || !Number.isInteger(region.y)
      || region.x < 0 || region.x >= 16384 || region.y < 0 || region.y >= 16384) {
      throw new Error('Invalid building region coordinates')
    }
    const key = `${region.z}/${region.x}/${region.y}`, rows = groups.get(key)
    if (rows) rows.push(region)
    else groups.set(key, [region])
  }
  return groups
}

export function mergePublishedFootprints(rows: Footprint[][]): Footprint[] {
  const components = new Map<string, Footprint>()
  for (const features of rows) {
    if (!Array.isArray(features)) throw new Error('Invalid published footprints')
    for (const feature of features) {
      const holes = (feature as Footprint & { holes?: unknown }).holes
      components.set(JSON.stringify([feature.key, feature.ring, holes ?? null]), feature)
    }
  }
  return [...components.values()]
}

export function retainPublishedKeys(leaves: Map<string, Footprint[]>, published: Footprint[]) {
  const decoded = new Set([...leaves.values()].flat().map(feature => feature.key))
  let retained = 0
  for (const feature of published) {
    if (decoded.has(feature.key)) continue
    const leaf = leaves.get(feature.key.split('/').slice(0, 3).join('/'))
    if (!leaf || !Number.isFinite(feature.z) || !Number.isFinite(feature.h)
      || !Array.isArray(feature.ring) || feature.ring.length < 3
      || feature.ring.some(point => point.length !== 2 || !point.every(Number.isFinite))) {
      throw new Error(`Cannot retain invalid published footprint ${JSON.stringify({ key: feature.key,
        leafAvailable: Boolean(leaf), z: feature.z, h: feature.h,
        ringLength: feature.ring?.length, invalidPoint: feature.ring?.find(point => point.length !== 2 || !point.every(Number.isFinite)) })}`)
    }
    leaf.push(structuredClone(feature)); retained++
  }
  return retained
}

export async function readRegionFilter(path?: string): Promise<Set<string> | undefined> {
  if (!path) return undefined
  const keys: unknown = JSON.parse(await readFile(path, 'utf8'))
  if (!Array.isArray(keys) || keys.some(key => typeof key !== 'string' || !/^14\/\d+\/\d+$/.test(key)
    || key.split('/').slice(1).some(n => Number(n) >= 2 ** 14))) throw new Error('Invalid region filter')
  return new Set(keys as string[])
}

export function preservesCoverage(previous: { coverage?: string[] } | undefined, coverage: string[]) {
  if (!previous) return true
  return previous.coverage ? previous.coverage.every(key => coverage.includes(key)) : coverage.length === 16
}

export async function createUnpublishedRegionFolder(root: string, baseId: string) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const id = attempt ? `${baseId}-${randomUUID().slice(0, 8)}` : baseId
    const folder = join(root, id)
    try { await mkdir(folder); return { id, folder } } catch (error: any) {
      if (error.code !== 'EEXIST') throw error
    }
  }
  throw new Error('Cannot allocate unpublished building region')
}

export async function readBuildingCatalog(path: string): Promise<{ source?: string; regions: any[] }> {
  try {
    const data = JSON.parse(await readFile(path, 'utf8'))
    if (!Array.isArray(data.regions)) throw new Error('Invalid building catalog')
    return data
  } catch (error: any) {
    if (error.code === 'ENOENT') return { regions: [] }
    throw error
  }
}

export async function regionAssetsComplete(output: string, region: { id: string; groundPolicy?: string; groundRevision?: string; counts?: Record<string, number> }) {
  try {
    const folder = join(output, region.id)
    const tree = JSON.parse(await readFile(join(folder, 'tileset.json'), 'utf8'))
    const footprints = JSON.parse(await readFile(join(folder, 'footprints.json'), 'utf8'))
    if (!Array.isArray(footprints)) return false
    if (region.counts && footprints.length !== Object.values(region.counts).reduce((a, b) => a + b, 0)) return false
    if (region.groundPolicy === 'local-dem' || region.groundPolicy === 'layered-ground-v1') {
      const source = JSON.parse(await readFile(join(folder, 'ground-source.json'), 'utf8'))
      if (!region.groundRevision || source.fileSignature !== region.groundRevision) return false
    }
    const pending = [tree.root], files = new Set<string>()
    while (pending.length) {
      const node = pending.pop(), uri = node?.content?.uri
      if (typeof uri !== 'string' || !/^[\w-]+\.b3dm$/.test(uri)) return false
      files.add(uri)
      if (node.children && !Array.isArray(node.children)) return false
      pending.push(...(node.children || []))
      if (files.size + pending.length > 128) return false
    }
    return (await Promise.all([...files].map(async uri => {
      const file = await open(join(folder, uri), 'r')
      try {
        const info = await file.stat(), header = Buffer.alloc(12)
        const { bytesRead } = await file.read(header, 0, 12, 0)
        return bytesRead === 12 && info.size >= 28 && header.toString('ascii', 0, 4) === 'b3dm'
          && header.readUInt32LE(4) === 1 && header.readUInt32LE(8) === info.size
      } finally { await file.close() }
    }))).every(Boolean)
  } catch { return false }
}
