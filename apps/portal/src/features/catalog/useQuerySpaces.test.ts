import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {authenticated, unauthenticated} from '../../test/authFixtures';
import {useQuerySpaces} from './useQuerySpaces';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {SharedConnectionStatus} from '../shared-spaces/sharedSpaces.types';

// The AWS boundary only: the real `useConnections` → cache-read chain runs, so a change
// to what "usable" means is caught here rather than mocked over.
vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));

const mockCache = vi.mocked(readSharedConnectionsCache);

function withShared(connections: {name: string; role: string; status: SharedConnectionStatus}[]) {
  mockCache.mockResolvedValue({success: true, data: {version: 1, connections}} as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  withShared([]);
});

afterEach(() => {
  vi.unstubAllEnvs();
});

const render = () => renderHookWithProviders(() => useQuerySpaces(), {auth: authenticated('alice')});

describe('useQuerySpaces (SPEC-173 FR-005)', () => {
  it('puts the user’s own space first', async () => {
    const {result} = render();

    await waitFor(() =>
      expect(result.current[0]).toEqual({
        id: 'personal',
        label: 'alice',
        bucket: 'user-space',
        rootPrefix: 'alice/',
        rootLabel: 'My Files'
      })
    );
  });

  it('adds one entry per usable shared space, in connections order', async () => {
    withShared([
      {name: 'project_alpha', role: 'member', status: 'active'},
      {name: 'teamspace', role: 'owner', status: 'active'}
    ]);

    const {result} = render();

    await waitFor(() => expect(result.current.map((s) => s.id)).toEqual(['personal', 'project_alpha', 'teamspace']));
    expect(result.current[1]).toEqual({
      id: 'project_alpha',
      label: 'project_alpha',
      bucket: 'shared-space',
      rootPrefix: 'project_alpha/',
      rootLabel: 'project_alpha'
    });
  });

  it.each(['provisioning', 'failed', 'leaving'] as SharedConnectionStatus[])(
    'omits a %s connection',
    async (status) => {
      withShared([
        {name: 'ready', role: 'member', status: 'active'},
        {name: 'notready', role: 'member', status}
      ]);

      const {result} = render();

      await waitFor(() => expect(result.current.map((s) => s.id)).toEqual(['personal', 'ready']));
    }
  );

  it('is the personal space alone with no shared bucket', async () => {
    vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', '');
    withShared([{name: 'project_alpha', role: 'member', status: 'active'}]);

    const {result} = render();

    await waitFor(() => expect(result.current.map((s) => s.id)).toEqual(['personal']));
  });

  it('is EMPTY with no signed-in user, rather than a space rooted at the bucket root', async () => {
    // The dev-unauth path renders the workspace with no user. An empty username used to
    // build `rootPrefix: '/'`, which would hold a marker open and list saved queries at
    // the BUCKET root — new S3 traffic where SPEC-043's hook was simply disabled.
    const {result} = renderHookWithProviders(() => useQuerySpaces(), {auth: unauthenticated()});

    await waitFor(() => expect(result.current).toEqual([]));
  });

  it('is EMPTY with no user-space bucket — a configuration error, not an empty list', async () => {
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', '');

    const {result} = render();

    await waitFor(() => expect(result.current).toEqual([]));
  });
});
