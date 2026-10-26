import { expect, test } from 'bun:test'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { preparedMapFile } from './prepared-map-files'

test('terrain archives serve exact byte ranges, suffixes and unsatisfiable requests', async () => {
  const root=await mkdtemp(join(tmpdir(),'terrain-range-'))
  const parts=['world-terrain','snapshot.pmtiles']
  try {
    await mkdir(join(root,'world-terrain'));await writeFile(join(root,...parts),'0123456789')
    const r=await preparedMapFile(parts,root,false,undefined,'bytes=2-5')
    expect(r.status).toBe(206);expect(r.headers.get('content-range')).toBe('bytes 2-5/10');expect(await r.text()).toBe('2345')
    expect(await (await preparedMapFile(parts,root,false,undefined,'bytes=-3')).text()).toBe('789')
    const invalid=await preparedMapFile(parts,root,false,undefined,'bytes=20-30')
    expect(invalid.status).toBe(416);expect(invalid.headers.get('content-range')).toBe('bytes */10')
    const head=await preparedMapFile(parts,root,true,undefined,'bytes=8-99')
    expect(head.headers.get('content-length')).toBe('2');expect(head.body).toBeNull()
  } finally {await rm(root,{recursive:true,force:true})}
})

test('files published after an earlier miss become available without a startup index', async () => {
  const root = await mkdtemp(join(tmpdir(), 'map-publication-'))
  try {
    const parts = ['world-ground', `${'a'.repeat(64)}.json`]
    expect((await preparedMapFile(parts, root)).status).toBe(404)
    await mkdir(join(root, parts[0]!))
    await writeFile(join(root, ...parts), '{"published":true}')
    const response = await preparedMapFile(parts, root)
    expect(await response.json()).toEqual({ published: true })
    expect(response.headers.get('cache-control')).toContain('immutable')
    await writeFile(join(root, parts[0]!, 'catalog.json'), '{"version":1}')
    await writeFile(join(root, parts[0]!, 'upload-plan.json'), '{"path":"private-local-path"}')
    expect((await preparedMapFile([parts[0]!, 'upload-plan.json'], root)).status).toBe(404)
    expect((await preparedMapFile([parts[0]!, 'catalog.json'], root, true)).headers.get('cache-control')).toBe('no-store')
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('only prepared map assets are served; traversal, alternate streams and unrelated files are refused', async () => {
  for (const parts of [[], ['other', 'catalog.json'], ['world-ground', '..', 'secret.json'],
    ['world-ground', '../secret.json'], ['world-ground', 'x\\secret.json'], ['world-ground', '.env'],
    ['world-ground', 'x.json:secret'], ['world-ground', '%2e%2e', 'secret.json']]) {
    expect((await preparedMapFile(parts, tmpdir())).status).toBe(404)
  }
})

test('a disconnected request stops an unread file stream', async () => {
  const root = await mkdtemp(join(tmpdir(), 'map-abort-'))
  try {
    await mkdir(join(root, 'world-ground'))
    await writeFile(join(root, 'world-ground', 'large.json'), ' '.repeat(1024 * 1024))
    const controller = new AbortController()
    const response = await preparedMapFile(['world-ground', 'large.json'], root, false, controller.signal)
    controller.abort()
    await expect(response.arrayBuffer()).rejects.toThrow()
    // HEAD never creates a read stream.
    const head = await preparedMapFile(['world-ground', 'large.json'], root, true)
    expect(head.body).toBeNull()
  } finally { await rm(root, { recursive: true, force: true }) }
})
