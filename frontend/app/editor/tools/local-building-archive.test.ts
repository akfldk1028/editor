import { test, expect } from 'bun:test'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { openLocalArchive } from './local-building-archive'

test('local archive reads byte ranges without HTTP and clamps the final range', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'map-archive-')), path = join(folder, 'archive')
  await writeFile(path, new Uint8Array([10, 20, 30, 40, 50]))
  const source = await openLocalArchive(path)
  try {
    expect([...new Uint8Array((await source.getBytes(1, 3)).data)]).toEqual([20, 30, 40])
    expect([...new Uint8Array((await source.getBytes(4, 100)).data)]).toEqual([50])
    await expect(source.getBytes(0, 1, AbortSignal.abort())).rejects.toThrow()
    await expect(source.getBytes(-1, 1)).rejects.toThrow('Invalid archive range')
  } finally { await source.close(); await rm(folder, { recursive: true }) }
})

test('a modified archive is refused instead of mixing snapshots', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'map-archive-')), path = join(folder, 'archive')
  await writeFile(path, 'original')
  const source = await openLocalArchive(path)
  try {
    await writeFile(path, 'changed-and-expanded')
    await expect(source.getBytes(0, 4)).rejects.toThrow('changed during publication')
  } finally { await source.close(); await rm(folder, { recursive: true }) }
})
