import { expect, test } from 'bun:test'
import { replacePublishedFile } from './replace-published-file'

test('publication retries transient reader locks without losing the old destination', async () => {
  let attempts = 0, current = 'old'
  await replacePublishedFile('next', 'catalog', async () => {
    if (++attempts < 4) throw Object.assign(new Error('locked'), { code: 'EPERM' })
    current = 'new'
  }, async () => { expect(current).toBe('old') })
  expect(attempts).toBe(4)
  expect(current).toBe('new')
})

test('publication bounds persistent locking retries and does not retry missing sources', async () => {
  for (const code of ['EPERM', 'ENOENT']) {
    let attempts = 0
    await expect(replacePublishedFile('next', 'catalog', async () => {
      attempts++; throw Object.assign(new Error(code), { code })
    }, async () => {})).rejects.toThrow(code)
    expect(attempts).toBe(code === 'EPERM' ? 10 : 1)
  }
})
