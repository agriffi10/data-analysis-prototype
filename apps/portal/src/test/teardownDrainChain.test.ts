import {describe, it, expect} from 'vitest';
import {notifyManager} from '@tanstack/query-core';

/**
 * Fixture for the drain LOOP in `src/test-setup.ts`. Nothing in the suite chains notifications,
 * so without this the loop could be cut back to a single yield and no test would notice.
 *
 * One test, alone in its file on purpose: the check that catches this runs in `afterAll`, and a
 * following test's own macrotasks would deliver the outstanding generations before it got there.
 */
describe('the teardown drain, against a notification chain', () => {
  it('follows a notification that schedules the next one', () => {
    // Queued and deliberately NOT awaited, so all three generations are still outstanding when
    // the test ends. A drain that yields once delivers the first and leaves the rest queued, and
    // the setup file's teardown check then refuses this file.
    notifyManager.schedule(() => {
      notifyManager.schedule(() => {
        notifyManager.schedule(() => {});
      });
    });
    expect(true).toBe(true);
  });
});
