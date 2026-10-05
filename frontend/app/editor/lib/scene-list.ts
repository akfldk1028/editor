import { z } from 'zod'

const sceneSummary = z.object({
  id: z.string().min(1),
  name: z.string(),
  nodeCount: z.number().int().nonnegative(),
  updatedAt: z.string(),
  thumbnailUrl: z.string().nullable().optional(),
})

export type SceneSummary = z.infer<typeof sceneSummary>
export type SceneListResult =
  | { status: 'ready'; scenes: SceneSummary[] }
  | { status: 'error' }

type FetchSceneList = (url: string, options: RequestInit) => Promise<Response>

export async function loadSceneList(
  origin: string,
  basePath: string,
  fetcher: FetchSceneList = fetch,
): Promise<SceneListResult> {
  try {
    const response = await fetcher(`${origin.replace(/\/$/, '')}${basePath}/api/scenes?limit=50`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(15_000),
    })
    if (!response.ok) return { status: 'error' }
    const payload = await response.json()
    const parsed = z.array(sceneSummary).safeParse(Array.isArray(payload) ? payload : payload?.scenes)
    return parsed.success ? { status: 'ready', scenes: parsed.data } : { status: 'error' }
  } catch {
    return { status: 'error' }
  }
}
