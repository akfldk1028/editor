import { expect, test } from 'bun:test'
import { conversationErrorText } from './errors'

test('quota and authentication failures have distinct recovery guidance', () => {
  const quota = conversationErrorText('conversation_model_usage_limit')
  const auth = conversationErrorText('conversation_model_authentication')
  expect(quota).toBeTruthy()
  expect(auth).toBeTruthy()
  expect(quota).not.toEqual(auth)
  expect(quota).not.toContain('conversation_')
})

test('server error codes become user-facing recovery guidance without technical strings', () => {
  const codes = ['conversation_processing_failed', 'conversation_model_timeout', 'conversation_program_reconciliation_required', 'conversation_step_limit', 'conversation_interrupted', 'conversation_scheduling_failed']
  for (const code of codes) {
    const message = conversationErrorText(code)
    expect(message).toBeTruthy()
    expect(message).not.toContain('conversation_')
    expect(message).toContain('메시지')
  }
  expect(conversationErrorText('conversation_interrupted')).toContain('기존 메시지는 저장되어 있어요')
  expect(conversationErrorText('conversation_processing_failed')).toContain('새 메시지로 다시 보내')
  expect(conversationErrorText('conversation_program_reconciliation_required')).toContain('이전 반영 결과부터 확인')
})

test('unknown errors remain generic and absent errors render nothing', () => {
  expect(conversationErrorText('Internal traceback: secret')).not.toContain('Internal traceback')
  expect(conversationErrorText(null)).toBeNull()
  expect(conversationErrorText(undefined)).toBeNull()
})
