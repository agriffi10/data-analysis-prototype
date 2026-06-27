import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn(),
}));

import { readSharedConnectionsCache } from '../shared-spaces/sharedSpaces.service';
import { getSessionCredentials } from '../../lib/awsCredentials';
import { useConnections } from './useConnections';
import type { SharedConnectionsCache } from '../shared-spaces/sharedSpaces.types';

const mockRead = vi.mocked(readSharedConnectionsCache);
const mockForceRefresh = vi.mocked(getSessionCredentials);

function cache(connections: SharedConnectionsCache['connections']): SharedConnectionsCache {
  return { version: 1, connections };
}

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockForceRefresh.mockResolvedValue({
    success: true,
    data: {} as never,
  });
});

describe('useConnections (SPEC-052 FR-001)', () => {
  it('merges the personal database with shared entries (personal first, shared A–Z)', async () => {
    mockRead.mockResolvedValueOnce({
      success: true,
      data: cache([
        { name: 'zeta', role: 'member', status: 'active' },
        { name: 'alpha', role: 'owner', status: 'provisioning' },
      ]),
    });
    const { result } = renderHook(() => useConnections('alice'), {
      wrapper: wrapper(newClient()),
    });

    await waitFor(() => expect(result.current.connections).toHaveLength(3));
    expect(result.current.error).toBeNull();
    expect(result.current.connections).toEqual([
      { id: 'personal', label: 'alice', database: 'alice', kind: 'personal' },
      {
        id: 'alpha',
        label: 'alpha',
        database: 'alpha',
        kind: 'shared',
        status: 'provisioning',
        role: 'owner',
      },
      {
        id: 'zeta',
        label: 'zeta',
        database: 'zeta',
        kind: 'shared',
        status: 'active',
        role: 'member',
      },
    ]);
  });

  it('yields personal-only on a missing/empty cache (not an error)', async () => {
    mockRead.mockResolvedValueOnce({ success: true, data: cache([]) });
    const { result } = renderHook(() => useConnections('alice'), {
      wrapper: wrapper(newClient()),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.connections).toEqual([
      { id: 'personal', label: 'alice', database: 'alice', kind: 'personal' },
    ]);
  });

  it('surfaces a read error while leaving no connections (consumer falls back)', async () => {
    mockRead.mockResolvedValueOnce({
      success: false,
      error: { message: 'boom' },
    });
    const { result } = renderHook(() => useConnections('alice'), {
      wrapper: wrapper(newClient()),
    });

    await waitFor(() => expect(result.current.error).toBe('boom'));
  });

  it('returns an empty list and never reads the cache when username is null', async () => {
    const { result } = renderHook(() => useConnections(null), {
      wrapper: wrapper(newClient()),
    });
    expect(result.current.connections).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(mockRead).not.toHaveBeenCalled();
  });

  it('refresh forces a credential refresh, then re-reads the cache', async () => {
    mockRead.mockResolvedValueOnce({ success: true, data: cache([]) });
    const { result } = renderHook(() => useConnections('alice'), {
      wrapper: wrapper(newClient()),
    });
    await waitFor(() => expect(result.current.connections).toHaveLength(1));
    expect(mockRead).toHaveBeenCalledTimes(1);

    // The pipeline has since flipped a connection to active; Refresh picks it up.
    mockRead.mockResolvedValueOnce({
      success: true,
      data: cache([{ name: 'team', role: 'owner', status: 'active' }]),
    });
    await act(async () => {
      await result.current.refresh();
    });

    expect(mockForceRefresh).toHaveBeenCalledWith(true);
    await waitFor(() => expect(result.current.connections).toHaveLength(2));
    expect(result.current.connections[1].database).toBe('team');
  });
});
