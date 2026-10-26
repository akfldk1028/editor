import { expect, test } from 'bun:test'
import { addCurrentSetback } from './setback-load'

test('a retired parcel cannot add its delayed regulation geometry', async () => {
  let resolve!: (value: any) => void
  let current = true
  const added: any[] = []
  const viewer = { isDestroyed: () => false, dataSources: { add: (value: any) => added.push(value), remove() {} } }
  const pending = addCurrentSetback(new Promise(r => { resolve = r }), viewer, () => current, 'setbacks')
  current = false
  resolve({ name: '' })
  await pending
  expect(added).toHaveLength(0)
  await addCurrentSetback(Promise.resolve({ name: '' }), viewer, () => true, 'setbacks')
  expect(added).toEqual([{ name: 'setbacks' }])
})

test('a destroyed viewer never receives a completed source', async () => {
  let calls = 0
  await addCurrentSetback(Promise.resolve({}), { isDestroyed: () => true, dataSources: { add: () => calls++, remove() {} } }, () => true, 'setbacks')
  expect(calls).toBe(0)
})

test('clearing during Cesium asynchronous collection insertion removes the retired source', async () => {
  let current = true
  const added: any[] = [], removed: any[] = []
  const source = { name: '' }
  const viewer = { isDestroyed: () => false, dataSources: {
    add: async (value: any) => { current = false; await Promise.resolve(); added.push(value) },
    remove: (value: any, destroy: boolean) => { removed.push([value, destroy]) },
  } }
  await addCurrentSetback(Promise.resolve(source), viewer, () => current, 'setbacks')
  expect(added).toEqual([source])
  expect(removed).toEqual([[source, true]])
})
