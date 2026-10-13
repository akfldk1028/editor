import { afterEach, expect, test } from 'bun:test'
import { currentConversation, newConversation, selectConversationProject } from './session'

const realFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = realFetch; selectConversationProject(null) })

/** The backend's answer to "start a conversation": a binding of the same project on a branch of its own. */
function serves(status: number) {
  const asked: string[] = []
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    asked.push(`${init?.method ?? 'GET'} ${String(url)}`)
    const body = { project_id: 'p1-c', owner_project_id: 'owner', branch_id: 'c-0123456789ab', scene_id: 's', scene_revision: 1, scene_project_id: null }
    return new Response(JSON.stringify(status === 201 ? body : { detail: 'no' }), { status })
  }) as typeof fetch
  return asked
}

test('a new conversation moves to a workspace of its own: the same project on its own branch', async () => {
  const asked = serves(201)
  selectConversationProject('p1')
  await newConversation()
  expect(asked).toEqual(['POST /api/v1/platform/projects/p1/conversations'])
  expect(currentConversation().projectId).toBe('p1-c')
  expect(currentConversation().conversationId).not.toBe('main')
})

test('when the workspace cannot be made, the new conversation still starts in the current project', async () => {
  serves(500)
  selectConversationProject('p1')
  await newConversation()
  expect(currentConversation().projectId).toBe('p1')
  expect(currentConversation().conversationId).not.toBe('main')
})

test('"새 대화" pressed while the project is still loading starts a new conversation once it is known', async () => {
  serves(201)
  await newConversation()
  expect(currentConversation().projectId).toBeNull()
  selectConversationProject('p1')
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(currentConversation().projectId).toBe('p1-c')
  // Only that one press: choosing another project later keeps its own saved conversation.
  selectConversationProject('p2')
  expect(currentConversation().conversationId).toBe('main')
})
