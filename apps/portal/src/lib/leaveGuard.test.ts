import {afterEach, describe, expect, it, vi} from 'vitest';
import {downloadTextFile} from './downloadTextFile';
import {armLeaveGuard, disarmLeaveGuard, isLeaveGuardDisarmed, withoutLeaveGuard} from './leaveGuard';

afterEach(() => {
  armLeaveGuard();
  vi.restoreAllMocks();
});

describe('the leave guard', () => {
  it('runs an action disarmed and puts the guard back as it was', () => {
    const during: boolean[] = [];

    withoutLeaveGuard(() => during.push(isLeaveGuardDisarmed()));
    disarmLeaveGuard();
    withoutLeaveGuard(() => during.push(isLeaveGuardDisarmed()));

    expect(during).toEqual([true, true]);
    // Restored, not re-armed: a sign-out already under way stays disarmed.
    expect(isLeaveGuardDisarmed()).toBe(true);
  });

  it('puts the guard back after an action that throws', () => {
    expect(() =>
      withoutLeaveGuard(() => {
        throw new Error('click failed');
      })
    ).toThrow('click failed');

    expect(isLeaveGuardDisarmed()).toBe(false);
  });

  it('lets a text file download without asking', () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:portal/1');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const disarmedDuringClick: boolean[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {
      disarmedDuringClick.push(isLeaveGuardDisarmed());
    });

    downloadTextFile('query.sql', 'SELECT 1', 'application/sql');

    expect(disarmedDuringClick).toEqual([true]);
    expect(isLeaveGuardDisarmed()).toBe(false);
  });
});
