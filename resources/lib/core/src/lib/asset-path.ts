/**
 * Resolve a path into the editor's public asset tree.
 *
 * The editor is served at the root on its own, and under `/editor` when it is
 * one surface of the PLAN product shell. An absolute `/icons/wall.webp` is
 * correct in the first case and a 404 in the second — and `next/image` does not
 * prefix it, so every node icon silently fails there.
 *
 * `NEXT_PUBLIC_BASE_PATH` is inlined at build time, so this works in packages
 * that know nothing about the app hosting them.
 */
const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH ?? '').replace(/\/$/, '')

export function assetPath(path: string): string {
  if (!BASE_PATH) return path
  // Idempotent: an icon may be resolved where it is declared and again where it
  // is rendered, and prefixing twice would 404 as surely as not prefixing at all.
  if (path === BASE_PATH || path.startsWith(`${BASE_PATH}/`)) return path
  // Leave anything already addressed elsewhere alone.
  if (/^[a-z]+:/i.test(path) || path.startsWith('//') || path.startsWith('data:')) return path
  return path.startsWith('/') ? `${BASE_PATH}${path}` : `${BASE_PATH}/${path}`
}

/** The base path the editor is mounted at, or an empty string at the root. */
export const assetBasePath = BASE_PATH
