import {vi} from 'vitest';

/**
 * Runs `body` on vitest's fake clock, with Testing Library able to drive that clock.
 *
 * Testing Library settles every `user.click` and `findBy*` through a `setTimeout(0)`, and it
 * advances a fake clock to reach that timeout only when it finds a `jest` global. Vitest has
 * none, so under a bare `vi.useFakeTimers()` a full-page render hangs on its first click. The
 * `jest` stand-in exposes the one method Testing Library calls. It is assigned and removed by
 * hand rather than through `vi.stubGlobal`, because `vi.unstubAllGlobals` would also undo stubs
 * the test set up for itself.
 *
 * Fake `Date` comes with the fake clock, so anything stamped with `Date.now()` (TanStack's
 * `dataUpdatedAt` included) moves with `vi.advanceTimersByTimeAsync`.
 *
 * @param body - The test, run with fake timers installed.
 * @returns Whatever `body` resolves to.
 *
 * @example
 * await withFakeTimers(async () => {
 *   await user.click(screen.getByRole('button', {name: 'Run statement'}));
 *   await act(() => vi.advanceTimersByTimeAsync(MAX_POLL_DURATION_MS));
 * });
 */
export async function withFakeTimers<T>(body: () => Promise<T>): Promise<T> {
  const host = globalThis as {jest?: unknown};
  const hadJest = 'jest' in host;
  const previous = host.jest;
  vi.useFakeTimers();
  host.jest = {advanceTimersByTime: (ms: number) => vi.advanceTimersByTime(ms)};
  try {
    return await body();
  } finally {
    if (hadJest) host.jest = previous;
    else delete host.jest;
    vi.useRealTimers();
  }
}
