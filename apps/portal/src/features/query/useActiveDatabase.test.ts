import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useActiveDatabase } from './useActiveDatabase';
import { QUERY_ACTIVE_DB_STORAGE_PREFIX } from './query.constants';
import type { Connection } from './query.types';

const personal: Connection = {
  id: 'personal',
  label: 'My workspace',
  database: 'alice',
  kind: 'personal',
};
const shared: Connection = {
  id: 's1',
  label: 'Project Alpha',
  database: 'project_alpha',
  kind: 'shared',
  status: 'active',
  role: 'member',
};

function key(username: string) {
  return `${QUERY_ACTIVE_DB_STORAGE_PREFIX}${username}`;
}

beforeEach(() => {
  sessionStorage.clear();
});

describe('useActiveDatabase (SPEC-047 FR-002)', () => {
  it('defaults to the personal database when nothing is persisted', () => {
    const { result } = renderHook(() => useActiveDatabase('alice', [personal]));
    expect(result.current.activeDatabase).toBe('alice');
  });

  it('restores the persisted database across reloads', () => {
    sessionStorage.setItem(key('alice'), 'project_alpha');
    const { result } = renderHook(() =>
      useActiveDatabase('alice', [personal, shared]),
    );
    expect(result.current.activeDatabase).toBe('project_alpha');
  });

  it('setActiveDatabase updates and persists the choice', () => {
    const { result } = renderHook(() =>
      useActiveDatabase('alice', [personal, shared]),
    );
    act(() => result.current.setActiveDatabase('project_alpha'));
    expect(result.current.activeDatabase).toBe('project_alpha');
    expect(sessionStorage.getItem(key('alice'))).toBe('project_alpha');
  });

  it('falls back to personal (with a dismissible notice) when the persisted DB is gone', () => {
    // A shared DB the user once selected is no longer in the connections list.
    sessionStorage.setItem(key('alice'), 'project_alpha');
    const { result } = renderHook(() => useActiveDatabase('alice', [personal]));
    expect(result.current.activeDatabase).toBe('alice');
    expect(result.current.fellBack).toBe(true);

    act(() => result.current.dismissFellBack());
    expect(result.current.fellBack).toBe(false);
    // Still resolves to personal even after dismissing the notice.
    expect(result.current.activeDatabase).toBe('alice');
  });

  it('falls back to personal when the active shared DB flips to non-usable (SPEC-052 FR-004)', () => {
    // The targeted shared DB is still LISTED (so the rail can show its status) but
    // has been revoked — status no longer 'active'. It must not stay the target.
    sessionStorage.setItem(key('alice'), 'project_alpha');
    const leaving: Connection = { ...shared, status: 'leaving' };
    const { result } = renderHook(() =>
      useActiveDatabase('alice', [personal, leaving]),
    );
    expect(result.current.activeDatabase).toBe('alice');
    expect(result.current.fellBack).toBe(true);
  });

  it('re-applies a stored database once it becomes available again', () => {
    sessionStorage.setItem(key('alice'), 'project_alpha');
    const { result, rerender } = renderHook(
      ({ conns }) => useActiveDatabase('alice', conns),
      { initialProps: { conns: [personal] as Connection[] } },
    );
    expect(result.current.activeDatabase).toBe('alice'); // unavailable → personal

    rerender({ conns: [personal, shared] });
    expect(result.current.activeDatabase).toBe('project_alpha'); // sticky preference
  });

  it('defaults cleanly with no crash when there is no username', () => {
    const { result } = renderHook(() => useActiveDatabase(null, []));
    expect(result.current.activeDatabase).toBe('');
    expect(result.current.fellBack).toBe(false);
  });
});
