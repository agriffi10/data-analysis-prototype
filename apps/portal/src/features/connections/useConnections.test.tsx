import {describe, it, expect, vi, beforeEach} from 'vitest';
import {waitFor, act} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';

// Boundary-only mocks (react.md §21): the shared-connections cache read and the
// token re-mint are the seam. Everything else — the hook's merge,
// ordering, reconcile/refresh, polling window — runs for real.
vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
vi.mock('../../lib/idToken', () => ({getIdToken: vi.fn()}));

import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {getIdToken} from '../../lib/idToken';
import {useConnections} from './useConnections';
import type {SharedConnectionsCache} from '../shared-spaces/sharedSpaces.types';

const mockRead = vi.mocked(readSharedConnectionsCache);
const mockForceRefresh = vi.mocked(getIdToken);

function cache(connections: SharedConnectionsCache['connections']): SharedConnectionsCache {
  return {version: 1, connections};
}

beforeEach(() => {
  vi.clearAllMocks();
  mockForceRefresh.mockResolvedValue({success: true, data: {} as never});
});

describe('useConnections (SPEC-052 FR-001)', () => {
  it('merges the personal database with shared entries (personal first, shared A–Z)', async () => {
    mockRead.mockResolvedValueOnce({
      success: true,
      data: cache([
        {name: 'zeta', role: 'member', status: 'active'},
        {name: 'alpha', role: 'owner', status: 'provisioning'}
      ])
    });
    const {result} = renderHookWithProviders(() => useConnections('alice'));

    await waitFor(() => expect(result.current.connections).toHaveLength(3));
    expect(result.current.error).toBeNull();
    expect(result.current.connections).toEqual([
      {id: 'personal', label: 'alice', database: 'alice', kind: 'personal'},
      {id: 'alpha', label: 'alpha', database: 'alpha', kind: 'shared', status: 'provisioning', role: 'owner'},
      {id: 'zeta', label: 'zeta', database: 'zeta', kind: 'shared', status: 'active', role: 'member'}
    ]);
  });

  it('yields personal-only on a missing/empty cache (not an error)', async () => {
    mockRead.mockResolvedValueOnce({success: true, data: cache([])});
    const {result} = renderHookWithProviders(() => useConnections('alice'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.connections).toEqual([{id: 'personal', label: 'alice', database: 'alice', kind: 'personal'}]);
  });

  it('surfaces a read error while leaving no connections (consumer falls back)', async () => {
    mockRead.mockResolvedValueOnce({success: false, error: {message: 'boom'}});
    const {result} = renderHookWithProviders(() => useConnections('alice'));

    await waitFor(() => expect(result.current.error).toEqual(expect.objectContaining({message: 'boom'})));
  });

  it('returns an empty list and never reads the cache when username is null', () => {
    const {result} = renderHookWithProviders(() => useConnections(null));
    expect(result.current.connections).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(mockRead).not.toHaveBeenCalled();
  });

  it('refresh forces a credential refresh, then re-reads the cache', async () => {
    mockRead.mockResolvedValueOnce({success: true, data: cache([])});
    const {result} = renderHookWithProviders(() => useConnections('alice'));
    await waitFor(() => expect(result.current.connections).toHaveLength(1));
    expect(mockRead).toHaveBeenCalledTimes(1);

    // The pipeline has since flipped a connection to active; Refresh picks it up.
    mockRead.mockResolvedValueOnce({success: true, data: cache([{name: 'team', role: 'owner', status: 'active'}])});
    await act(async () => {
      await result.current.refresh();
    });

    expect(mockForceRefresh).toHaveBeenCalledWith(true);
    await waitFor(() => expect(result.current.connections).toHaveLength(2));
    expect(result.current.connections[1].database).toBe('team');
  });

  it('reconcile re-mints the token and re-reads the cache (auto-resolves a submitted action)', async () => {
    mockRead.mockResolvedValueOnce({success: true, data: cache([])});
    const {result} = renderHookWithProviders(() => useConnections('alice'));
    await waitFor(() => expect(result.current.connections).toHaveLength(1));

    // The just-submitted create lands in the cache; reconcile picks it up without a
    // manual Refresh, and re-mints the token so the actor can use the new space.
    mockRead.mockResolvedValue({success: true, data: cache([{name: 'team', role: 'owner', status: 'active'}])});
    await act(async () => {
      await result.current.reconcile();
    });

    expect(mockForceRefresh).toHaveBeenCalledWith(true);
    await waitFor(() => expect(result.current.connections).toHaveLength(2));
    expect(result.current.connections[1].database).toBe('team');
  });
});
