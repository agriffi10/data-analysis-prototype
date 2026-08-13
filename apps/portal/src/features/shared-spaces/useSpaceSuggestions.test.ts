import {beforeEach, describe, expect, it, vi} from 'vitest';
import {waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {authenticated, unauthenticated} from '../../test/authFixtures';
import {useSpaceSuggestions} from './useSpaceSuggestions';
import {readSharedConnectionsCache} from './sharedSpaces.service';
import {buildIndex} from '../user-directory/usernameTrie';
import {connectionKeys} from '../connections/connectionKeys';
import type {SharedConnectionEntry} from './sharedSpaces.types';

vi.mock('./sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn()
}));

// The REAL ranking, wrapped in a spy: SPEC-158 FR-003 forbids a second implementation, and the
// rebuild claim is asserted by counting calls rather than by timing a handful of names (a timing
// budget over five strings proves nothing — the SPEC-147 lesson).
vi.mock('../user-directory/usernameTrie', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../user-directory/usernameTrie')>();
  return {...actual, buildIndex: vi.fn(actual.buildIndex)};
});

describe('useSpaceSuggestions', () => {
  const active = (name: string): SharedConnectionEntry => ({name, role: 'member', status: 'active'});

  const cache = (connections: SharedConnectionEntry[]) => ({
    success: true as const,
    data: {version: 1 as const, connections}
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(readSharedConnectionsCache).mockResolvedValue(cache([active('salesteam'), active('salesops')]));
  });

  function render(options: Parameters<typeof renderHookWithProviders>[1] = {}) {
    return renderHookWithProviders(() => useSpaceSuggestions(), options);
  }

  async function ready(rendered: ReturnType<typeof render>) {
    await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
  }

  it('suggests the user’s shared spaces, ranked by the shared index', async () => {
    const rendered = render();
    expect(rendered.result.current.status).toBe('loading');
    expect(rendered.result.current.search('sales')).toEqual([]);

    await ready(rendered);

    expect(rendered.result.current.search('sales')).toEqual([
      {username: 'salesops', match: 'prefix'},
      {username: 'salesteam', match: 'prefix'}
    ]);
    expect(rendered.result.current.search('salesteam')).toEqual([{username: 'salesteam', match: 'exact'}]);
  });

  it('never suggests the personal database', async () => {
    // It is not a shared space, and the dialog reaches it as a USER recipient instead.
    const rendered = render({auth: authenticated('alice')});
    await ready(rendered);

    expect(rendered.result.current.search('alice')).toEqual([]);
  });

  it('drops spaces that are not usable yet', async () => {
    vi.mocked(readSharedConnectionsCache).mockResolvedValue(
      cache([
        {name: 'salesteam', role: 'member', status: 'provisioning'},
        {name: 'salesops', role: 'owner', status: 'leaving'},
        active('finance')
      ])
    );
    const rendered = render();
    await ready(rendered);

    expect(rendered.result.current.search('sales')).toEqual([]);
    expect(rendered.result.current.search('fin')).toEqual([{username: 'finance', match: 'prefix'}]);
  });

  it('collapses a failed read and a member of no space into "unavailable"', async () => {
    vi.mocked(readSharedConnectionsCache).mockResolvedValue({success: false, error: {message: 'boom'}});
    const failed = render();
    await waitFor(() => expect(failed.result.current.status).toBe('unavailable'));
    expect(failed.result.current.search('sales')).toEqual([]);

    vi.mocked(readSharedConnectionsCache).mockResolvedValue(cache([]));
    const empty = render();
    await waitFor(() => expect(empty.result.current.status).toBe('unavailable'));
    expect(empty.result.current.search('sales')).toEqual([]);
  });

  it('is unavailable, and reads nothing, with no signed-in user', async () => {
    const rendered = render({auth: unauthenticated()});

    expect(rendered.result.current.status).toBe('unavailable');
    expect(readSharedConnectionsCache).not.toHaveBeenCalled();
  });

  it('builds the index ONCE, however many times it is searched or re-rendered', async () => {
    const rendered = render();
    await ready(rendered);

    for (const query of ['s', 'sa', 'sal', 'sale', 'sales']) rendered.result.current.search(query);
    rendered.rerender();
    rendered.result.current.search('salesops');

    expect(buildIndex).toHaveBeenCalledTimes(1);
  });

  it('rebuilds only when the connection list changes', async () => {
    const rendered = render();
    await ready(rendered);
    rendered.result.current.search('sales');
    expect(buildIndex).toHaveBeenCalledTimes(1);

    rendered.queryClient.setQueryData(connectionKeys.list('alice'), {
      version: 1,
      connections: [active('salesteam'), active('salesops'), active('finance')]
    });
    await waitFor(() => expect(rendered.result.current.search('fin')).toHaveLength(1));

    expect(buildIndex).toHaveBeenCalledTimes(2);
  });
});
