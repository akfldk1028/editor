import { ClaudeCliProvider } from "./claude/claudeCliProvider.js";
import { CachedChatProvider } from "./cachedChatProvider.js";
import { CodexCliProvider } from "./codex/codexCliProvider.js";
import type { ChatProvider, ProviderId } from "./contracts.js";

export function createProviderRegistry(cwd = process.cwd()): Map<ProviderId, ChatProvider> {
  return new Map<ProviderId, ChatProvider>([
    ["codex", new CachedChatProvider(new CodexCliProvider(undefined, cwd))],
    ["claude", new CachedChatProvider(new ClaudeCliProvider(undefined, cwd))]
  ]);
}

export async function getProviderStatuses(providers: Map<ProviderId, ChatProvider>) {
  return Promise.all([...providers.values()].map((provider) => provider.getStatus()));
}
