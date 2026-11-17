import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, render, waitFor} from '@testing-library/react';
import {QueryClientProvider, type QueryClient} from '@tanstack/react-query';
import {AuthContext} from '../auth/authContext';
import {authLoading, authenticated} from '../../test/authFixtures';
import {apiRequest} from '../../lib/apiClient';
import {createQueryClient} from '../../lib/queryClient';
import {configValue} from '../../lib/runtimeConfig';
import {documentBody, mockApi, type ApiMock} from '../../test/apiMock';
import type {AuthContextValue} from '../auth/auth.types';
import {FEATURE_FLAG_DEFAULTS} from './featureFlagDefaults';
import {seedServerFlags} from './seedServerFlags';
import {useFeature} from './useFeature';
import {useFeatureFlags} from './useFeatureFlags';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

/**
 * A set the server sent, on a real query client built with the frame's own defaults and seeded only by
 * `seedServerFlags`: the harness's seed sets an infinite `staleTime` on the flag keys, under which a
 * wrong key or a missing `updatedAt` would still pass.
 */

const MINUTE = 60 * 1000;
const SEEDED = {...FEATURE_FLAG_DEFAULTS, query: false};

let api: ApiMock;
let client: QueryClient;

/** What the hooks answered on each render, in order. */
let seen: {status: string; query: boolean}[];

function Probe() {
  const {status} = useFeatureFlags();
  seen.push({status, query: useFeature('query')});
  return null;
}

/** The probe under the seeded client and the given auth, re-rendered in place by the returned function. */
function renderUnder(auth: AuthContextValue) {
  const tree = (value: AuthContextValue) => (
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={value}>
        <Probe />
      </AuthContext.Provider>
    </QueryClientProvider>
  );
  const {rerender} = render(tree(auth));
  return (next: AuthContextValue) => rerender(tree(next));
}

/** Let any fetch the query would start begin and settle. */
async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

beforeEach(() => {
  seen = [];
  client = createQueryClient();
  api = mockApi(vi.mocked(apiRequest));
  api.on('featureFlags.get', documentBody({version: 1, defaults: FEATURE_FLAG_DEFAULTS, environments: {}}));
});

afterEach(() => {
  client.clear();
  vi.clearAllMocks();
});

describe('a tab the server sent its flags', () => {
  it('is ready with the seeded set on its first render, while auth is still resolving', () => {
    seedServerFlags(client, configValue('environment'), {flags: SEEDED, readAt: Date.now()});

    renderUnder(authLoading());

    expect(seen[0]).toEqual({status: 'ready', query: false});
  });

  it('is not ready when the set was seeded under another environment’s key', () => {
    seedServerFlags(client, 'another-environment', {flags: SEEDED, readAt: Date.now()});

    renderUnder(authLoading());

    expect(seen[0].status).toBe('loading');
  });

  it('reads no flags once auth resolves when the set is fresh', async () => {
    seedServerFlags(client, configValue('environment'), {flags: SEEDED, readAt: Date.now()});
    const resolveAuth = renderUnder(authLoading());

    resolveAuth(authenticated());
    await flush();

    expect(api.countOf('featureFlags.get')).toBe(0);
    expect(seen.at(-1)).toEqual({status: 'ready', query: false});
  });

  it('reads the flags once auth resolves when the API answered the server 61 minutes ago', async () => {
    seedServerFlags(client, configValue('environment'), {flags: SEEDED, readAt: Date.now() - 61 * MINUTE});
    const resolveAuth = renderUnder(authLoading());

    resolveAuth(authenticated());
    await flush();

    await waitFor(() => expect(api.countOf('featureFlags.get')).toBe(1));
  });
});
