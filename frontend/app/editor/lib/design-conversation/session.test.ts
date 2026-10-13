import { expect, test } from 'bun:test'
import { currentConversation, newConversation, selectConversationProject } from './session'

test('"새 대화" pressed while the project is still loading starts a new conversation once it is known', () => {
  newConversation()
  expect(currentConversation().projectId).toBeNull()
  selectConversationProject('p1')
  const started = currentConversation().conversationId
  expect(started).not.toBe('main')
  // Only that one press: choosing another project later keeps its own saved conversation.
  selectConversationProject('p2')
  expect(currentConversation().conversationId).toBe('main')
})
