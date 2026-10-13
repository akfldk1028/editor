import { expect, test } from 'bun:test'
import type { RunQuestion } from '@/lib/orchestrator-runs/types'
import { asksForLot, lotChoices } from './lots'

const QUESTION: RunQuestion = {
  kind: 'request_input', code: 'district_lot_required', fields: ['district_lot'], pnu: '4115011300106840001',
  candidates: { status: 'parcel_not_tied_to_a_lot_choose_one', lots: [
    { lot: '공공1', bcr_pct_max: [{ value: 60, quote: '건폐율 ∙ 60퍼센트 이하', article: '제23조', document: '12차 고시문' }],
      far_pct_max: [{ value: 250, quote: '용적률 ∙ 250퍼센트 이하', article: '제23조' }], max_storeys: [{ value: 5 }],
      allowed_uses: [{ value: ['공공업무시설', '지역자치센터'], quote: '허용용도 ∙ …' }], lot_area_m2: 2500 },
    { lot: '' }, { lot: '근9-2', far_pct_max: [{ value: 350 }] },
  ] },
}

test('each offered lot shows what Law read, in words, with its quote and source, values untouched', () => {
  const [public1, near] = lotChoices(QUESTION)
  expect(lotChoices(QUESTION).map((choice) => choice.lot)).toEqual(['공공1', '근9-2'])
  expect(public1!.rows.map((row) => [row.label, row.values.map((value) => value.text)])).toEqual([
    ['건폐율', ['60% 이하']], ['용적률', ['250% 이하']], ['최고층수', ['5층 이하']], ['허용 용도', ['공공업무시설, 지역자치센터']]])
  expect(public1!.rows[0]!.values[0]).toEqual({ text: '60% 이하', quote: '건폐율 ∙ 60퍼센트 이하', source: '12차 고시문 · 제23조' })
  expect(public1!.others).toBe(1)
  expect(near!.rows).toEqual([{ label: '용적률', values: [{ text: '350% 이하', quote: null, source: null }] }])
})

test('only a question about the district lot that offers lots asks for one', () => {
  expect(asksForLot(QUESTION)).toBe(true)
  expect(asksForLot({ kind: 'request_input', fields: ['building_type'] })).toBe(false)
  expect(asksForLot({ ...QUESTION, candidates: { lots: [] } })).toBe(false)
  expect(asksForLot(null)).toBe(false)
})

test('a use list reads as its text, a figure with what it is measured from, a source by its file name', () => {
  const question: RunQuestion = { kind: 'request_input', fields: ['district_lot'], candidates: { lots: [{
    lot: 'A11', lot_basis: { document: '/data/ace/notices/365180/전라남도_2016-490호_고시.pdf', quote: '결정도 참조 : A11 ~ A12' },
    allowed_uses: [{ text: '공장; 창고시설', value: null, quote: '허용용도 …', document: '/data/ace/notices/365180/전라남도_2016-490호_고시.pdf', article: '마.1) 산업시설용지' }],
    building_line_m: [{ value: 8, text: '중로 2-54, 55호선변', quote: '…8m' }],
  }] } }
  const [a11] = lotChoices(question)
  expect(a11!.basis).toEqual({ quote: '결정도 참조 : A11 ~ A12', source: '전라남도_2016-490호_고시.pdf' })
  expect(a11!.rows.map((row) => [row.label, row.values[0]!.text])).toEqual([['건축한계선', '8 m (중로 2-54, 55호선변)'], ['허용 용도', '공장; 창고시설']])
  expect(a11!.rows[1]!.values[0]!.source).toBe('전라남도_2016-490호_고시.pdf · 마.1) 산업시설용지')
  expect(a11!.others).toBe(0)
})
