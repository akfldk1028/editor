import { expect, test } from 'bun:test'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { enrichLayeredGround, type GroundLayer } from './building-ground-layers'
import { verifyDemFiles } from './dem-file-stamps'
import type { Footprint } from '../features/world/lib/building-geometry'

test('installed raster sampler feeds precise overrides and NoData preservation through signed layers', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'ground-layers-'))
  const python = process.env.WORLD_PYTHON || 'python'
  try {
    const fixture = spawnSync(python, ['-c', `
import sys,numpy as np,rasterio
from pathlib import Path
from rasterio.transform import from_origin
for name,values in [('base',[10,20,-9999,-9999]),('precise',[12,-9999,30,-9999])]:
    with rasterio.open(Path(sys.argv[1])/(name+'.tif'),'w',driver='GTiff',width=4,height=1,count=1,dtype='float32',crs='EPSG:4326',transform=from_origin(126,38,1,1),nodata=-9999) as ds:
        ds.write(np.array([values],dtype='float32'),1)
`, directory], { encoding: 'utf8', windowsHide: true })
    if (fixture.status !== 0) throw new Error(fixture.stderr || String(fixture.error))
    const makeLayer = (name: string): GroundLayer => {
      const sample = async (points: number[][]) => {
        const result = spawnSync(python, [fileURLToPath(new URL('./sample-building-dem.py', import.meta.url)), join(directory, `${name}.tif`)],
          { input: JSON.stringify(points), encoding: 'utf8', windowsHide: true })
        if (result.status !== 0) throw new Error(result.stderr || String(result.error))
        return JSON.parse(result.stdout)
      }
      return { revision: '', sample }
    }
    const base = makeLayer('base'), precise = makeLayer('precise')
    for (const layer of [base, precise]) {
      const metadata = await layer.sample([]) as Awaited<ReturnType<GroundLayer['sample']>> & { revisionFiles: Parameters<typeof verifyDemFiles>[0] }
      layer.revision = metadata.source.fileSignature
      layer.verify = () => verifyDemFiles(metadata.revisionFiles)
    }
    const features: Footprint[] = [9, undefined, undefined, undefined].map((z, i) => ({
      key: String(i), pnu: '', ring: [[126.5 + i, 37.5]], h: 12, s: 'm', z,
    }))
    const result = await enrichLayeredGround(features, { base, precise })
    expect(features.map(f => f.z)).toEqual([12, 20, 30, undefined])
    expect(features.map(f => [f.h, f.s])).toEqual(Array.from({ length: 4 }, () => [12, 'm']))
    expect(result.metrics).toEqual({ beforeMissing: 3, newlyFilled: 2, preciseOverride: 1, remaining: 1 })
    expect(result.sources.precise?.raster).toBe('precise.tif')
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
}, 30000)
