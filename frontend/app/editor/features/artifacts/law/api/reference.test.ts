import { expect, test } from 'bun:test'
import { loadReference } from './reference'
import type { ReviewRef } from '../lib/review'

test('source retrieval retains full text and rejects a different ordinance or article', async () => {
  const original = globalThis.fetch
  const text = '원문 내용\n'.repeat(300)
  let name = '갑시 건축 조례'
  const ref: ReviewRef = { instrument: name, kind: 'ordinance', article: '제2조', clause: null, text: null, text_status: 'needs_source' }
  globalThis.fetch = (async url => Response.json(String(url).endsWith('/ensure') ? { up: ['law'], failed: [] } : {
    tool: 'law_ordinance', answer: { kind: 'ordinance', ordinance: { name, edition_id: 'edition' }, matches: [{ article: '제2조', text }, { article: '제3조', text: '다른 조문' }] },
  })) as typeof fetch
  try {
    const site = { pnu: 'parcel', assessmentDate: '2026-10-09' }
    expect((await loadReference(ref, site, new AbortController().signal)).text).toBe(text)
    name = '을시 건축 조례'
    await expect(loadReference(ref, site, new AbortController().signal)).rejects.toThrow('원문을 받지 못했습니다')
  } finally { globalThis.fetch = original }
})

test('name-only ordinance uses the agent to resolve the official dated edition', async () => {
  const original = globalThis.fetch
  const ref: ReviewRef = { instrument: '갑시 주차장 조례', kind: 'ordinance', article: null, clause: null, text: null, text_status: 'needs_source' }
  const url = 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=123'
  let asked = false
  globalThis.fetch = (async (input, init) => {
    if (String(input).endsWith('/ensure')) return Response.json({ up: ['law'], failed: [] })
    asked = true
    const body = JSON.parse(String(init?.body))
    expect(body.clause.refs[0].article).toBeNull()
    expect(body.assessment_date).toBe('2026-10-09')
    return Response.json({ tool: 'law_ordinance', answer: { kind: 'ordinance', ordinance: { name: ref.instrument, url, edition_id: '123' }, matches: [] } })
  }) as typeof fetch
  try {
    const result = await loadReference(ref, { pnu: 'parcel', assessmentDate: '2026-10-09' }, new AbortController().signal)
    expect(asked).toBe(true)
    expect(result.url).toBe(url)
    expect(result.text).toBe('')
  } finally { globalThis.fetch = original }
})

test('a whole ordinance with a verified edition reads its official full text without asking the agent', async () => {
  const original = globalThis.fetch
  const urls: string[] = []
  const url = 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=9'
  const annexes = [{ number: '1', title: '[별표 1] 표', kind: '서식', file_kind: 'hwpx', file_url: 'http://www.law.go.kr/flDownload.do?flSeq=1', content: null }]
  globalThis.fetch = (async (input, init) => {
    urls.push(String(input))
    expect(JSON.parse(String(init?.body))).toEqual({ name: '갑시 건축 조례', edition_id: '9', assessment_date: '2026-10-09' })
    return Response.json({ ordinance: { name: '갑시 건축 조례', edition_id: '9', effective_date: '2025-01-01', url }, articles: [{ article: '', heading: true, content: '제1장 총칙' }, { article: '제1조', heading: false, content: '제1조(목적) 내용' }], annexes, supplement: { content: '부칙 시행' } })
  }) as typeof fetch
  try {
    const ref: ReviewRef = { instrument: '갑시 건축 조례', kind: 'ordinance', article: null, clause: null, text: null, text_status: 'needs_source', url, edition_id: '9', effective_date: '2025-01-01' }
    expect(await loadReference(ref, { pnu: 'parcel', assessmentDate: '2026-10-09' }, new AbortController().signal))
      .toEqual({ text: '제1장 총칙\n\n제1조(목적) 내용\n\n부칙 시행', url, edition: '9', effective: '2025-01-01', annexes })
    expect(urls).toEqual(['/api/v1/platform/ordinances/body'])
    globalThis.fetch = (async () => Response.json({ error: 'identity_mismatch', reason: 'record differs in name' })) as typeof fetch
    await expect(loadReference(ref, { pnu: 'parcel', assessmentDate: '2026-10-09' }, new AbortController().signal)).rejects.toThrow('record differs in name')
  } finally { globalThis.fetch = original }
})
