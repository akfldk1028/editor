import { describe, expect, test } from 'bun:test'
import { loadSceneList } from './scene-list'

describe('scene list loading', () => {
  test('keeps an unavailable store distinct from an empty store', async () => {
    const result = await loadSceneList('http://editor.test', '', async () => new Response('', { status: 503 }))
    expect(result).toEqual({ status: 'error' })
    const empty = await loadSceneList('http://editor.test', '', async () => Response.json({ scenes: [] }))
    expect(empty).toEqual({ status: 'ready', scenes: [] })
  })

  test('uses the mounted base path and disables response caching', async () => {
    let calledUrl = ''
    let options: RequestInit | undefined
    const result = await loadSceneList('http://editor.test/', '/editor-app', async (url, init) => {
      calledUrl = String(url)
      options = init
      return Response.json({ scenes: [] })
    })
    expect(calledUrl).toBe('http://editor.test/editor-app/api/scenes?limit=50')
    expect(options?.cache).toBe('no-store')
    expect(result.status).toBe('ready')
  })

  test('does not interpret malformed or interrupted responses as empty', async () => {
    for (const payload of [{}, { scenes: null }, { scenes: [{ id: 'broken' }] }]) {
      expect(await loadSceneList('http://editor.test', '', async () => Response.json(payload))).toEqual({ status: 'error' })
    }
    expect(await loadSceneList('http://editor.test', '', async () => new Response('invalid json'))).toEqual({ status: 'error' })
    expect(await loadSceneList('http://editor.test', '', async () => { throw new Error('disconnected') })).toEqual({ status: 'error' })
  })

  test('accepts both supported list envelopes without losing displayed metadata', async () => {
    const scene = { id: 'scene-1', name: 'Saved plan', nodeCount: 12, updatedAt: '2026-10-05T00:00:00Z', thumbnailUrl: null }
    for (const payload of [[scene], { scenes: [scene] }]) {
      expect(await loadSceneList('http://editor.test', '', async () => Response.json(payload))).toEqual({ status: 'ready', scenes: [scene] })
    }
  })
})
