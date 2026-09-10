import {describe, it, expect, vi} from 'vitest';
import {notifyManager} from '@tanstack/query-core';

/**
 * Fixture for the real-`setTimeout` capture in `src/test-setup.ts`. Nothing in the suite leaves a
 * fake clock installed, so without this the capture could be replaced by the ambient global and
 * no test would notice — until a test forgot to restore its clock and the drain hung while
 * blaming a file that did nothing wrong.
 *
 * One test, alone in its file on purpose: it leaves the clock installed, and anything appended
 * after it would inherit that clock and hang on its first real timer.
 */
describe('the teardown drain, against a fake clock', () => {
  it('drains a queued notification even with a fake clock installed', () => {
    // Guards the guard: a clock left behind by an earlier test would make the swap below a no-op
    // and this fixture would silently stop testing anything.
    expect(vi.isFakeTimers()).toBe(false);

    // Scheduled on the REAL clock so the drain has work to do, and only then is the clock
    // swapped. The drain must reach a `setTimeout` the fake clock cannot intercept.
    notifyManager.schedule(() => {});
    vi.useFakeTimers();
  });
});
