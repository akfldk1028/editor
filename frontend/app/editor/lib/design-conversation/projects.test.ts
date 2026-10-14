import { afterEach, expect, test } from 'bun:test'
import { addProject, currentProjects, refreshProjects, resetProjects } from './projects'

const realFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = realFetch; resetProjects() })
const binding = (id: string) => ({ project_id: id, owner_project_id: 'o', branch_id: 'main', scene_id: 's', scene_revision: 1, scene_project_id: null })

test('every panel reads one list: a new workspace is known at once and refreshes share one request', async () => {
  let asked = 0
  globalThis.fetch = (async () => { asked += 1; return new Response(JSON.stringify([binding('a')]), { status: 200 }) }) as unknown as typeof fetch
  await Promise.all([refreshProjects(), refreshProjects()])
  expect(asked).toBe(1)
  expect(currentProjects().items.map((item) => item.project_id)).toEqual(['a'])
  addProject({ ...binding('c'), branch_id: 'c-0123456789ab', conversation: true })
  addProject(binding('a'))
  expect(currentProjects().items.map((item) => item.project_id)).toEqual(['a', 'c'])
})

test('a stale list response preserves a conversation created while it was loading', async () => {
  let finish!: (response: Response) => void
  globalThis.fetch = (() => new Promise<Response>((resolve) => { finish = resolve })) as typeof fetch
  const loading = refreshProjects()
  addProject({ ...binding('new'), conversation: true })
  finish(new Response(JSON.stringify([binding('old')]), { status: 200 }))
  await loading
  expect(currentProjects().items.map((item) => item.project_id)).toEqual(['old', 'new'])
})
