export class LatestRunRequest {
  private controller: AbortController | null = null;

  start(): AbortSignal {
    this.controller?.abort();
    this.controller = new AbortController();
    return this.controller.signal;
  }

  isCurrent(signal: AbortSignal): boolean {
    return !signal.aborted && this.controller?.signal === signal;
  }

  finish(signal: AbortSignal): void {
    if (this.controller?.signal === signal) {
      this.controller = null;
    }
  }

  abort(): void {
    this.controller?.abort();
    this.controller = null;
  }
}
