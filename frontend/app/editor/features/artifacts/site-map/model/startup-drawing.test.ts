import { expect, test } from 'bun:test'
import { readStartupDrawing, writeStartupDrawing } from './startup-drawing'

test('reload preview is scoped and never caches an unconfirmed click', () => {
  const values = new Map<string, string>()
  const storage = { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => { values.set(k, v) } }
  const drawn = { geometries: [{ type: 'Polygon', coordinates: [] }], outline: null, look: 'saved' as const }
  writeStartupDrawing('project-a', drawn, storage)
  expect(readStartupDrawing('project-a', storage)).toEqual(drawn)
  expect(readStartupDrawing('project-b', storage)).toBeNull()
  writeStartupDrawing('project-a', { ...drawn, look: 'picked' }, storage)
  expect(readStartupDrawing('project-a', storage)?.look).toBe('saved')
  storage.setItem('site-map.startup.v1:old', JSON.stringify({ at: 0, drawn }))
  expect(readStartupDrawing('old', storage)).toBeNull()
})
