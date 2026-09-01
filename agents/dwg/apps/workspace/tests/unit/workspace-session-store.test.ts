import assert from "node:assert/strict";
import test from "node:test";

import {
  appendWorkspaceMessage,
  createWorkspaceSession,
  createWorkspaceSessionStore
} from "../../src/features/agent-chat/workspaceSessionStore.js";

const codexSessionId = "019fa7ba-415a-7a90-8e86-7370a2dd4a2f";

test("creates a titled session and persists a bounded transcript", () => {
  const session = createWorkspaceSession({
    id: "workspace-1",
    provider: "codex",
    drawingPath: "tests/fixtures/dwg/export_sample.dwg",
    now: "2026-07-28T10:00:00.000Z",
    firstMessage: "0 레이어의 모든 객체를 근거와 함께 검사해줘."
  });

  assert.equal(session.title, "0 레이어의 모든 객체를 근거와 함께 검사해줘.");
  assert.equal(session.messages.length, 1);

  let current = session;
  for (let index = 0; index < 25; index += 1) {
    current = appendWorkspaceMessage(current, {
      id: `assistant-${index}`,
      role: "assistant",
      text: `response-${index}`,
      createdAt: `2026-07-28T10:00:${String(index).padStart(2, "0")}.000Z`
    });
  }
  assert.equal(current.messages.length, 20);
  assert.equal(current.messages.at(-1)?.text, "response-24");
});

test("session store keeps newest twenty sessions and valid provider UUIDs", () => {
  const values = new Map<string, string>();
  const store = createWorkspaceSessionStore({
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value)
  });

  for (let index = 0; index < 22; index += 1) {
    store.upsert({
      ...createWorkspaceSession({
        id: `workspace-${index}`,
        provider: index % 2 ? "claude" : "codex",
        drawingPath: "tests/fixtures/dwg/export_sample.dwg",
        now: `2026-07-28T10:${String(index).padStart(2, "0")}:00.000Z`,
        firstMessage: `session ${index}`
      }),
      providerSessionId: codexSessionId
    });
  }

  const sessions = store.list();
  assert.equal(sessions.length, 20);
  assert.equal(sessions[0].id, "workspace-21");
  assert.equal(sessions.at(-1)?.id, "workspace-2");
  assert.equal(store.get("workspace-21")?.providerSessionId, codexSessionId);
});

test("session store ignores malformed data and storage failures", () => {
  const malformed = createWorkspaceSessionStore({
    getItem: () => "{\"sessions\":[{\"provider\":\"unknown\"}]}",
    setItem: () => undefined
  });
  assert.deepEqual(malformed.list(), []);

  const blocked = createWorkspaceSessionStore({
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    }
  });
  const session = createWorkspaceSession({
    id: "memory-session",
    provider: "claude",
    drawingPath: "tests/fixtures/dwg/export_sample.dwg",
    now: "2026-07-28T10:00:00.000Z",
    firstMessage: "remember me"
  });
  blocked.upsert(session);
  assert.equal(blocked.get("memory-session")?.title, "remember me");
});
