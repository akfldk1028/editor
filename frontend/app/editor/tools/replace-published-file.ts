import { rename } from 'node:fs/promises'

export async function replacePublishedFile(from: string, to: string, move = rename,
  delay: (ms: number) => Promise<void> = ms => new Promise(resolve => setTimeout(resolve, ms))) {
  for (let attempt = 0; ; attempt++) {
    try { await move(from, to); return }
    catch (error) {
      if (attempt === 9 || !['EPERM', 'EACCES', 'EBUSY'].includes((error as NodeJS.ErrnoException).code ?? '')) throw error
      // Windows static-file readers briefly hold the destination. Never unlink
      // the last complete catalog while waiting for an atomic replacement.
      await delay(Math.min(1000, 50 * 2 ** attempt))
    }
  }
}
