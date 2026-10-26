import { open } from 'node:fs/promises'
import { resolve } from 'node:path'
import type { Source } from 'pmtiles'

export async function openLocalArchive(path: string): Promise<Source & { close: () => Promise<void> }> {
  const file = await open(path, 'r')
  const original = await file.stat()
  const key = `${resolve(path)}:${original.size}:${original.mtimeMs}`
  const unchanged = async () => {
    const current = await file.stat()
    if (current.size !== original.size || current.mtimeMs !== original.mtimeMs) throw new Error('Building archive changed during publication')
  }
  return {
    getKey: () => key,
    close: () => file.close(),
    async getBytes(offset, length, signal) {
      signal?.throwIfAborted()
      if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(length) || offset < 0 || length < 0) throw new Error('Invalid archive range')
      await unchanged()
      const data = new Uint8Array(Math.max(0, Math.min(length, original.size - offset)))
      let done = 0
      while (done < data.length) {
        signal?.throwIfAborted()
        const result = await file.read(data, done, data.length - done, offset + done)
        if (!result.bytesRead) throw new Error('Truncated building archive')
        done += result.bytesRead
      }
      await unchanged()
      signal?.throwIfAborted()
      return { data: data.buffer, etag: key }
    },
  }
}
