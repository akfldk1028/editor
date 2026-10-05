import { test, expect } from 'bun:test'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { productPath } from '../../planm/src/app/product-path'
import { getProject } from '../../planm/src/features/agent-workspace/api/projects'
import { runUrl } from '../../planm/src/features/agent-workspace/api/runs'

test('reused project API and run links retain the native mount prefix', async () => {
  const previous = process.env.NEXT_PUBLIC_BASE_PATH
  const fetchBefore = globalThis.fetch
  const urls: string[] = []
  process.env.NEXT_PUBLIC_BASE_PATH = '/editor'
  globalThis.fetch = (async url => {
    urls.push(String(url))
    return Response.json({ project_id: 'binding', owner_project_id: 'owner', branch_id: 'main', scene_id: 'scene', scene_revision: 2, scene_project_id: null })
  }) as typeof fetch
  try {
    expect(productPath('/projects/binding')).toBe('/editor/projects/binding')
    expect(runUrl('binding', 'run')).toBe('/editor/runs/run?project_id=binding')
    expect((await getProject('binding')).project_id).toBe('binding')
    expect(urls).toEqual(['/editor/api/v1/platform/projects/binding'])
  } finally {
    globalThis.fetch = fetchBefore
    if (previous === undefined) delete process.env.NEXT_PUBLIC_BASE_PATH
    else process.env.NEXT_PUBLIC_BASE_PATH = previous
  }
})

test('the original Vite surface remains usable without a process global', () => {
  const source = readFileSync(new URL('../../planm/src/app/product-path.ts', import.meta.url), 'utf8')
  const script = new Bun.Transpiler({ loader: 'ts' }).transformSync(source).replace('export function', 'function')
  expect(runInNewContext(script + '\nproductPath("/projects")')).toBe('/projects')
})
