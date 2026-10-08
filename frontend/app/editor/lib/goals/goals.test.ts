import { expect, test } from 'bun:test'

import { availableGoal, FALLBACK, offeredGoals } from './index'

test('the conversation offers only goals the door takes and the catalog marks to offer', () => {
  const catalog = { ...FALLBACK, goals: [
    ...FALLBACK.goals,
    { id: 'health', label: '에이전트 상태 확인', owners: [], inputs: [], optional: [], available: true, offer: false },
    { id: 'mass', label: '매스 생성', owners: ['program', 'masterplan', 'mass', 'revision'], inputs: ['pnu'], optional: [], available: false, offer: true },
  ] }
  expect(offeredGoals(catalog).map((goal) => goal.id)).toEqual(['limits'])
  expect(availableGoal(catalog, 'limits')?.owners).toEqual(['site_context', 'law', 'revision'])
  expect(availableGoal(catalog, 'mass')).toBeNull()
  expect(availableGoal(catalog, 'nope')).toBeNull()
  expect(FALLBACK.goals.map((goal) => goal.id)).toEqual(['limits'])
})
