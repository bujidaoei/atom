/** Retry only an explicit truncated completion, never ambiguous tool failures. */
export async function runWithRecovery<T>(options: {
  run(recovery: boolean): Promise<T>;
  signal: AbortSignal;
  onRecover(attempt: number, maxAttempts: number): void;
  maxAttempts?: number;
}): Promise<T> {
  const maximum = options.maxAttempts ?? 2;
  for (let attempt = 0; ; attempt++) {
    options.signal.throwIfAborted();
    try {
      return await options.run(attempt > 0);
    } catch (error) {
      options.signal.throwIfAborted();
      if (!(error instanceof Error) ||
          !error.message.includes('AI gateway response was truncated before completion') ||
          attempt >= maximum) throw error;
      options.onRecover(attempt + 1, maximum);
    }
  }
}
