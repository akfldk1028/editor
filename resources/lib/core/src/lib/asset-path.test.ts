import { describe, expect, test } from 'bun:test'

/**
 * `assetPath` reads NEXT_PUBLIC_BASE_PATH once at module load, so each case
 * imports a fresh copy with the variable already set.
 */
async function load(basePath: string | undefined) {
  const previous = process.env.NEXT_PUBLIC_BASE_PATH
  if (basePath === undefined) delete process.env.NEXT_PUBLIC_BASE_PATH
  else process.env.NEXT_PUBLIC_BASE_PATH = basePath
  const module = await import(`./asset-path?${Math.random()}`)
  if (previous === undefined) delete process.env.NEXT_PUBLIC_BASE_PATH
  else process.env.NEXT_PUBLIC_BASE_PATH = previous
  return module as typeof import('./asset-path')
}

describe('assetPath', () => {
  test('leaves paths alone when the editor is served at the root', async () => {
    const { assetPath } = await load(undefined)

    expect(assetPath('/icons/wall.webp')).toBe('/icons/wall.webp')
  })

  test('prefixes public assets when mounted under a path', async () => {
    const { assetPath } = await load('/editor')

    expect(assetPath('/icons/wall.webp')).toBe('/editor/icons/wall.webp')
  })

  test('is idempotent', async () => {
    const { assetPath } = await load('/editor')

    // An icon is resolved where it is declared and again where it is rendered;
    // prefixing twice would 404 as surely as not prefixing at all.
    expect(assetPath(assetPath('/icons/wall.webp'))).toBe('/editor/icons/wall.webp')
  })

  test('leaves an absolute URL alone', async () => {
    const { assetPath } = await load('/editor')

    expect(assetPath('https://cdn.example.com/a.webp')).toBe('https://cdn.example.com/a.webp')
    expect(assetPath('//cdn.example.com/a.webp')).toBe('//cdn.example.com/a.webp')
    expect(assetPath('data:image/webp;base64,AAAA')).toBe('data:image/webp;base64,AAAA')
  })

  test('handles a relative path and a trailing slash on the base', async () => {
    const { assetPath } = await load('/editor/')

    expect(assetPath('icons/wall.webp')).toBe('/editor/icons/wall.webp')
  })
})
