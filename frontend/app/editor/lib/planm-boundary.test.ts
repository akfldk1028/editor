// The PLANM feature is consumed through the `@planm/*` alias, never by reaching across apps with
// relative paths. Mirror of frontend/app/planm/tests/module-boundaries.test.mjs.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, test } from 'bun:test'

const root = join(import.meta.dir, '..')
const scanned = ['app', 'lib', 'components', 'features']
// This test reads the planm source text on purpose to pin product-path's behaviour.
const exempt = new Set(['lib/product-path.test.ts'])

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' || name === '.next' ? [] : files(path)
    return /\.(ts|tsx)$/.test(name) ? [path] : []
  })
}

describe('planm boundary', () => {
  test('no relative import reaches into frontend/app/planm', () => {
    const offenders: string[] = []
    for (const dir of scanned) {
      let entries: string[] = []
      try { entries = files(join(root, dir)) } catch { continue }
      for (const file of entries) {
        const rel = relative(root, file).replaceAll('\\', '/')
        if (exempt.has(rel)) continue
        const source = readFileSync(file, 'utf8')
        if (/from\s+['"](?:\.\.\/)+planm\//.test(source) || /import\(['"](?:\.\.\/)+planm\//.test(source)) offenders.push(rel)
      }
    }
    expect(offenders).toEqual([])
  })
})
