import { expect, test } from 'bun:test'
import { useExecutionStore } from './executionStore'
test('multimodal user messages keep text and renderable images instead of object children', () => {
  useExecutionStore.getState().clearSession()
  useExecutionStore.getState().addWSMessage({ type: 'message', data: { source: 'user', content: ['Review image', { data: 'iVBORw0KGgo=' }] } })
  const turn = useExecutionStore.getState().turns[0]
  expect(turn?.content).toBe('Review image')
  expect(turn?.images).toEqual(['data:image/png;base64,iVBORw0KGgo='])
})
