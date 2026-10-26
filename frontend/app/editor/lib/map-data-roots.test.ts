import { test, expect } from 'bun:test'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { preparedMapAsset } from './map-data-roots'

test('external data root supplies new files and retains existing local fallback', async () => {
  const root = await mkdtemp(join(tmpdir(), 'map-data-root-')), old = process.env.DATA_ROOT
  const data = join(root, 'data'), local = join(root, 'public')
  process.env.DATA_ROOT = data
  try {
    await mkdir(join(data, 'world-buildings'), { recursive: true }); await mkdir(join(local, 'world-buildings'), { recursive: true })
    await writeFile(join(data, 'world-buildings/latest.json'), '{"version":2}')
    await writeFile(join(local, 'world-buildings/catalog.json'), '{"version":1}')
    expect(await (await preparedMapAsset(['world-buildings', 'latest.json'], local)).json()).toEqual({ version: 2 })
    expect(await (await preparedMapAsset(['world-buildings', 'catalog.json'], local)).json()).toEqual({ version: 1 })
    expect((await preparedMapAsset(['world-buildings', '..', 'secret.json'], local)).status).toBe(404)
  } finally { if (old === undefined) delete process.env.DATA_ROOT; else process.env.DATA_ROOT = old; await rm(root, { recursive: true, force: true }) }
})

test('release pointer and building ranges are public but management receipts are not', async () => {
  const root=await mkdtemp(join(tmpdir(),'release-root-')),old=process.env.DATA_ROOT
  process.env.DATA_ROOT=root
  try {
    await mkdir(join(root,'releases'),{recursive:true});await writeFile(join(root,'releases/current.json'),'{"releaseId":"one"}')
    const response=await preparedMapAsset(['releases','current.json'],join(root,'public'))
    expect(await response.json()).toEqual({releaseId:'one'});expect(response.headers.get('cache-control')).toBe('no-store')
    await mkdir(join(root,'tiles/buildings/20261009-2f30a80f'),{recursive:true})
    await writeFile(join(root,'tiles/buildings/20261009-2f30a80f/buildings.pmtiles'),'0123456789')
    const range=await preparedMapAsset(['buildings','20261009-2f30a80f','buildings.pmtiles'],join(root,'public'),false,undefined,'bytes=2-5')
    expect(range.status).toBe(206);expect(await range.text()).toBe('2345')
    expect((await preparedMapAsset(['management','storage-registry.json'],root)).status).toBe(404)
    expect((await preparedMapAsset(['releases','a'.repeat(64),'files.json'],root)).status).toBe(404)
  } finally {if(old===undefined)delete process.env.DATA_ROOT;else process.env.DATA_ROOT=old;await rm(root,{recursive:true,force:true})}
})
