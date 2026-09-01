import assert from "node:assert/strict";
import test from "node:test";

import { CachedChatProvider } from "../../src/providers/cachedChatProvider.js";
import type {
  ChatProvider,
  ProviderChatRequest,
  ProviderStatus
} from "../../src/providers/contracts.js";

class CountingProvider implements ChatProvider {
  readonly id = "codex" as const;
  statusCalls = 0;

  async getStatus(): Promise<ProviderStatus> {
    this.statusCalls += 1;
    return {
      id: this.id,
      label: "GPT · Codex",
      installed: true,
      authenticated: true,
      authMethod: "chatgpt",
      detail: "ready"
    };
  }

  async chat(_request: ProviderChatRequest) {
    return {
      provider: this.id,
      text: "ok",
      sessionId: null
    };
  }
}

test("provider status cache reuses a fresh authentication result", async () => {
  const delegate = new CountingProvider();
  const provider = new CachedChatProvider(delegate, 30_000, () => 1_000);

  const first = await provider.getStatus();
  const second = await provider.getStatus();

  assert.equal(first, second);
  assert.equal(delegate.statusCalls, 1);
});

test("provider status cache refreshes after its TTL", async () => {
  const delegate = new CountingProvider();
  let now = 1_000;
  const provider = new CachedChatProvider(delegate, 30_000, () => now);

  await provider.getStatus();
  now += 30_001;
  await provider.getStatus();

  assert.equal(delegate.statusCalls, 2);
});

test("provider status cache delegates chat without changing the result", async () => {
  const provider = new CachedChatProvider(new CountingProvider());

  const result = await provider.chat({
    message: "도면을 설명해줘",
    systemPrompt: "근거만 사용",
    context: "handle=23D"
  });

  assert.deepEqual(result, {
    provider: "codex",
    text: "ok",
    sessionId: null
  });
});
