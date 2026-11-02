import { test, expect } from 'bun:test'
import { mkdtemp, writeFile, stat, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { verifyDemFiles } from './dem-file-stamps'
test('publication guard checks underlying rasters as well as the VRT', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'dem-guard-'))
  try {
    const files = await Promise.all(['source.vrt', 'block.tif'].map(async name => {
      const path = join(folder, name); await writeFile(path, 'initial')
      const s = await stat(path, { bigint: true })
      return { path, size: String(s.size), mtimeNs: String(s.mtimeNs) }
    }))
    await verifyDemFiles(files)
    await writeFile(files[1]!.path, 'changed raster')
    await expect(verifyDemFiles(files)).rejects.toThrow('DEM source changed')
    await expect(verifyDemFiles([])).rejects.toThrow('empty')
  } finally { await rm(folder, { recursive: true }) }
})
