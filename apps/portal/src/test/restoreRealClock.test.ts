import {describe, expect, it, vi} from 'vitest';

/**
 * Fixture for the real-clock restore in `src/test-setup.ts`. No other test leaves a clock for the
 * restore to remove, so without this the restore could be deleted as redundant and the suite would
 * stay green, until a test timed out on a loaded machine and its clock stalled the tests after it.
 *
 * The first test leaves its clock installed, as a test Vitest times out does, and the second must
 * start on the real one. They rely on running in order in one file, which Vitest does unless the
 * config shuffles.
 */
describe('the real-clock restore after every test', () => {
  it('leaves a fake clock installed, as a timed-out test would', () => {
    vi.useFakeTimers();

    expect(vi.isFakeTimers()).toBe(true);
  });

  it('starts the next test on the real clock', () => {
    expect(vi.isFakeTimers()).toBe(false);
  });
});
