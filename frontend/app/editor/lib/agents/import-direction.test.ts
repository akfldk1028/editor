import { expect, test } from 'bun:test'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

import { AGENTS, canonicalAgent, markOf, ORCHESTRATOR, toolOwner, toolSpecLabel, USER } from './index'

const ROOT = join(import.meta.dir, '..', '..')

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) files(path, out)
    else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(path)
  }
  return out
}

const imports = (path: string) => [...readFileSync(path, 'utf8').matchAll(/from '([^']+)'/g)].map((match) => match[1]!)

test('every agent folder declares itself and the registry derives the rest', () => {
  const ids = AGENTS.map((agent) => agent.id)
  expect(ids).toHaveLength(new Set(ids).size)
  expect(ids).toContain(ORCHESTRATOR)
  expect(ids).toContain(USER)
  expect(ids.length).toBeGreaterThanOrEqual(18)
  expect(canonicalAgent('site-context')).toBe('site_context')
  expect(canonicalAgent('planm')).toBe('plan')
  expect(canonicalAgent('nobody')).toBe('nobody')
  expect(toolOwner('law_parcel_limits')).toBe('law')
  expect(toolOwner('masterplan_anything')).toBe('masterplan')
  expect(toolOwner('site_health')).toBe('site_context')
  expect(toolOwner('x')).toBeNull()
  expect(toolSpecLabel('site_resolve')).toBe('대지 사실 확인')
  expect(markOf('law').tint).toBeDefined()
  expect(markOf('orchestrator').tint).toBeUndefined()
  expect(markOf('nobody').icon).toBeDefined()
  // One folder per agent, each with a spec and a mark.
  const folders = readdirSync(import.meta.dir).filter((name) => statSync(join(import.meta.dir, name)).isDirectory())
  expect(folders.length).toBe(AGENTS.length)
  for (const folder of folders) {
    expect(statSync(join(import.meta.dir, folder, 'model', 'spec.ts')).isFile()).toBe(true)
    expect(statSync(join(import.meta.dir, folder, 'ui', 'mark.tsx')).isFile()).toBe(true)
  }
})

test('shared code never imports features; agent folders never import the hooks that post them', () => {
  const offenders: string[] = []
  for (const path of files(join(ROOT, 'lib', 'agents'))) {
    for (const spec of imports(path)) {
      if (spec.includes('/features/') || /orchestrator-runs\/(useRunFeed|useAsk|connection)/.test(spec)) offenders.push(`${relative(ROOT, path)} → ${spec}`)
    }
  }
  for (const path of files(join(ROOT, 'lib', 'orchestrator-runs'))) {
    for (const spec of imports(path)) if (spec.includes('/features/')) offenders.push(`${relative(ROOT, path)} → ${spec}`)
  }
  expect(offenders).toEqual([])
})
