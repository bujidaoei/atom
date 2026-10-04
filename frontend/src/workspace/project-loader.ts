/** One active snapshot read, one trailing invalidation, immediate first display. */
export class ProjectLoader<T> {
  private active: Promise<void> | undefined;
  private controller: AbortController | undefined;
  private pending = false;
  private disposed = false;

  constructor(private readonly options: {
    read: (signal: AbortSignal) => Promise<T>;
    apply: (value: T) => void;
    fail: (error: unknown) => void;
    timeoutMs?: number;
  }) {}

  refresh(): Promise<void> {
    if (this.disposed) return Promise.resolve();
    if (this.active) {
      this.pending = true;
      return this.active;
    }
    // Defer execution so even synchronously settled reads see the active slot.
    this.active = Promise.resolve().then(() => this.drain()).finally(() => {
      this.active = undefined;
    });
    return this.active;
  }

  dispose(): void {
    this.disposed = true;
    this.pending = false;
    this.controller?.abort();
  }

  private async drain(): Promise<void> {
    do {
      this.pending = false;
      if (this.disposed) return;
      const controller = new AbortController();
      this.controller = controller;
      const timer = setTimeout(() => controller.abort(new Error(
        "工作区读取超时，请重试。")), this.options.timeoutMs ?? 15_000);
      try {
        const value = await this.options.read(controller.signal);
        if (!this.disposed) this.options.apply(value);
      } catch (error) {
        if (!this.disposed) this.options.fail(controller.signal.aborted
          ? controller.signal.reason : error);
      } finally {
        clearTimeout(timer);
        this.controller = undefined;
      }
    } while (this.pending && !this.disposed);
  }
}
