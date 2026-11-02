import { stat } from 'node:fs/promises'
export type DemFileStamp = { path: string; size: string; mtimeNs: string }
export async function verifyDemFiles(files: DemFileStamp[]) {
  if (!files.length) throw new Error('DEM source file list is empty')
  for (let start = 0; start < files.length; start += 32) {
    await Promise.all(files.slice(start, start + 32).map(async file => {
      const current = await stat(file.path, { bigint: true })
      if (String(current.size) !== file.size || String(current.mtimeNs) !== file.mtimeNs) throw new Error('DEM source changed during publication')
    }))
  }
}
