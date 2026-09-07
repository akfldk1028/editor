/**
 * Removes build caches across the monorepo.
 *
 * A shell one-liner is not usable here: bun's own shell — which `bun run` uses
 * on Windows — treats a glob that matches nothing as a fatal error, so a single
 * absent directory (a fresh clone has no `.turbo` anywhere) aborts the whole
 * command before it deletes the caches that do exist.
 */
import { readdir, rm } from 'node:fs/promises'
import path from 'node:path'

const repositoryRoot = path.resolve(import.meta.dirname, '../..')

/** Directories whose immediate children are workspace packages. */
const PACKAGE_PARENTS = [
  'frontend/app',
  'frontend/components',
  'frontend/elements',
  'backend',
  'resources/lib',
  'infra/config',
]

const CACHE_NAMES = ['.next', '.turbo', '.swc']

const targets: string[] = []

for (const parent of PACKAGE_PARENTS) {
  let packages: string[]
  try {
    packages = await readdir(path.join(repositoryRoot, parent))
  } catch {
    continue
  }
  for (const pkg of packages) {
    for (const cache of CACHE_NAMES) {
      targets.push(path.join(repositoryRoot, parent, pkg, cache))
    }
  }
}

targets.push(path.join(repositoryRoot, '.turbo'), path.join(repositoryRoot, 'node_modules/.cache'))

await Promise.all(targets.map((target) => rm(target, { recursive: true, force: true })))

console.log(`Cleared build caches under ${PACKAGE_PARENTS.length} package roots`)
