import type {
  ChatProvider,
  ProviderChatRequest,
  ProviderChatResult,
  ProviderStatus
} from "./contracts.js";

export class CachedChatProvider implements ChatProvider {
  readonly id;
  private cachedStatus: ProviderStatus | null = null;
  private cachedAt = 0;
  private pendingStatus: Promise<ProviderStatus> | null = null;

  constructor(
    private readonly delegate: ChatProvider,
    private readonly ttlMs = 30_000,
    private readonly now = Date.now
  ) {
    this.id = delegate.id;
  }

  async getStatus(): Promise<ProviderStatus> {
    if (this.cachedStatus && this.now() - this.cachedAt < this.ttlMs) {
      return this.cachedStatus;
    }
    if (this.pendingStatus) return this.pendingStatus;

    this.pendingStatus = this.delegate.getStatus().then((status) => {
      this.cachedStatus = status;
      this.cachedAt = this.now();
      return status;
    }).finally(() => {
      this.pendingStatus = null;
    });
    return this.pendingStatus;
  }

  chat(request: ProviderChatRequest): Promise<ProviderChatResult> {
    return this.delegate.chat(request);
  }
}
