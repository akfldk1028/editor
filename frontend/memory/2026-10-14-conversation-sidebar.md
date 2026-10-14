# Conversation sidebar (2026-10-14)

- The far-left shell sidebar owns new chat, title search, recent conversation groups and selection. Tools remain available in a separate section.
- Preserve the CAD module: `DwgWorkspaceProvider`, `DwgSidebar`, `DwgSidebarActions`, drawing sessions, project/layer navigation and skills remain unchanged. The supplied sidebar slot is mounted inside `CAD · 도면과 레이어`; `CAD 작업 열기` restores the CAD conversation and artifact. Choosing a saved chat switches the center to the agent conversation.
- Conversation identity comes from `ProjectBinding.conversation_id`, persisted by the backend. Browser storage retains only selection/legacy recovery. Failed creation leaves the previous conversation intact.
- Accepted messages update the shared project's title and activity immediately. List refreshes retain local additions/updates that happened while the request was in flight.
- Browser regression: `node --test infra/e2e/conversation-sidebar.test.mjs` against the registered editor dev server. Platform responses are isolated fixtures; it verifies search, creation, title, storage-free restoration, creation failure, CAD state retention and mobile drawer navigation.
- Backend schema v4 adds nullable `conversation_id` and `updated_at`. Existing conversation workspaces recover a unique identity from ledger records scoped to owner project + branch; ambiguous/missing records are not guessed. A successful legacy conversation read can remember its identity too.
