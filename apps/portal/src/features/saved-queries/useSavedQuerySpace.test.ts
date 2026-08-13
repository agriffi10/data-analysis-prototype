import {act, renderHook} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {useSavedQuerySpace} from './useSavedQuerySpace';
import {QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX} from './savedQueries.constants';
import type {QuerySpace} from '../catalog/catalog.types';

const PERSONAL: QuerySpace = {
  id: 'personal',
  label: 'My files',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};
const TEAM: QuerySpace = {
  id: 'teamspace',
  label: 'teamspace',
  bucket: 'shared-space',
  rootPrefix: 'teamspace/',
  rootLabel: 'teamspace'
};

const KEY = `${QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX}alice`;

beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe('useSavedQuerySpace (SPEC-174 FR-001)', () => {
  it('resolves to the personal space with nothing stored', () => {
    const {result} = renderHook(() => useSavedQuerySpace('alice', [PERSONAL, TEAM]));
    expect(result.current.space).toEqual(PERSONAL);
    expect(result.current.spaces).toEqual([PERSONAL, TEAM]);
  });

  it('remembers the chosen space, per user, for the session', () => {
    const {result} = renderHook(() => useSavedQuerySpace('alice', [PERSONAL, TEAM]));
    act(() => result.current.selectSpace('teamspace'));

    expect(result.current.space).toEqual(TEAM);
    expect(sessionStorage.getItem(KEY)).toBe('teamspace');
    // A second mount in the same session restores it.
    const again = renderHook(() => useSavedQuerySpace('alice', [PERSONAL, TEAM]));
    expect(again.result.current.space).toEqual(TEAM);
    // Another user's drawer is unaffected — the key carries the username.
    const bob = renderHook(() => useSavedQuerySpace('bob', [PERSONAL, TEAM]));
    expect(bob.result.current.space).toEqual(PERSONAL);
  });

  it('falls back to personal for a stored space that is no longer offered', () => {
    // A membership revoked mid-session, or the `sharedWorkspaces` flag turning off:
    // either way the id names nothing in the current list.
    sessionStorage.setItem(KEY, 'teamspace');
    const {result} = renderHook(() => useSavedQuerySpace('alice', [PERSONAL]));
    expect(result.current.space).toEqual(PERSONAL);
  });

  it('falls back to personal for an unparseable or empty stored value', () => {
    sessionStorage.setItem(KEY, '');
    expect(renderHook(() => useSavedQuerySpace('alice', [PERSONAL, TEAM])).result.current.space).toEqual(PERSONAL);
    sessionStorage.setItem(KEY, '{"not":"an id"}');
    expect(renderHook(() => useSavedQuerySpace('alice', [PERSONAL, TEAM])).result.current.space).toEqual(PERSONAL);
  });

  it('swallows a storage read AND a storage write that throw', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('disabled');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });

    const {result} = renderHook(() => useSavedQuerySpace('alice', [PERSONAL, TEAM]));
    expect(result.current.space).toEqual(PERSONAL);
    // The choice still applies in-tree; only the remembering is lost.
    act(() => result.current.selectSpace('teamspace'));
    expect(result.current.space).toEqual(TEAM);
  });

  it('is null only when there is no space at all', () => {
    expect(renderHook(() => useSavedQuerySpace('alice', [])).result.current.space).toBeNull();
    // No username means no storage key, and the first space still resolves.
    expect(renderHook(() => useSavedQuerySpace(null, [PERSONAL])).result.current.space).toEqual(PERSONAL);
  });
});
