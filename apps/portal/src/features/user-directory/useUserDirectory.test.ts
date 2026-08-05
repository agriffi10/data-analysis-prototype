import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {act, waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {unauthenticated} from '../../test/authFixtures';
import {useUserDirectory} from './useUserDirectory';
import {getUserDirectory} from './userDirectory.service';
import {MAX_INDEXED_USERNAMES, buildIndex} from './usernameTrie';

vi.mock('./userDirectory.service', () => ({getUserDirectory: vi.fn()}));
// `spy: true` keeps the real trie and only counts the calls — the point is how OFTEN the
// index is built, not what it returns.
vi.mock('./usernameTrie', {spy: true});

const directory = (usernames: string[], generatedAt = '2026-08-05T04:00:11Z') => ({
  success: true as const,
  data: {usernames, generatedAt}
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(buildIndex).mockClear();
  vi.mocked(getUserDirectory).mockResolvedValue(directory(['alice', 'bob_smith', 'cara']));
});

afterEach(() => {
  vi.restoreAllMocks();
});

const ready = async () => {
  const rendered = renderHookWithProviders(() => useUserDirectory());
  await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
  return rendered;
};

describe('useUserDirectory — status', () => {
  it('is loading before the document arrives and ready after', async () => {
    const {result} = renderHookWithProviders(() => useUserDirectory());
    expect(result.current.status).toBe('loading');

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.generatedAt).toBe('2026-08-05T04:00:11Z');
  });

  it('collapses an errored fetch to unavailable', async () => {
    vi.mocked(getUserDirectory).mockResolvedValue({success: false, error: {message: 'boom'}});
    const {result} = renderHookWithProviders(() => useUserDirectory());

    await waitFor(() => expect(result.current.status).toBe('unavailable'));
  });

  it('collapses an EMPTY document to unavailable too', async () => {
    // From a consumer's point of view "the fetch failed" and "there is nobody in it" are the
    // same situation: there are no suggestions to offer.
    vi.mocked(getUserDirectory).mockResolvedValue(directory([]));
    const {result} = renderHookWithProviders(() => useUserDirectory());

    await waitFor(() => expect(result.current.status).toBe('unavailable'));
  });

  it('does not fetch at all when there is no signed-in user', async () => {
    const {result} = renderHookWithProviders(() => useUserDirectory(), {auth: unauthenticated()});

    expect(result.current.status).toBe('unavailable');
    expect(getUserDirectory).not.toHaveBeenCalled();
  });
});

describe('useUserDirectory — search', () => {
  it('returns [] while the directory is not ready', () => {
    const {result} = renderHookWithProviders(() => useUserDirectory());

    expect(result.current.status).toBe('loading');
    expect(result.current.search('ali')).toEqual([]);
  });

  it('searches the fetched document', async () => {
    const {result} = await ready();

    expect(result.current.search('bob').map((r) => r.username)).toEqual(['bob_smith']);
  });

  it('keeps a stable identity across unrelated re-renders', async () => {
    const {result, rerender} = await ready();
    const first = result.current.search;

    rerender();
    rerender();

    expect(result.current.search).toBe(first);
  });

  it('builds the index ONCE, however many times it is searched or re-rendered', async () => {
    // Counted, not timed. A timing budget over a three-name directory passes just as happily
    // when the trie is rebuilt on every single call — which is exactly what an earlier version
    // of this test failed to notice.
    const {result, rerender} = await ready();

    for (let n = 0; n < 20; n += 1) {
      result.current.search('a');
      rerender();
    }

    expect(vi.mocked(buildIndex)).toHaveBeenCalledTimes(1);
    expect(result.current.search('a').map((r) => r.username)).toEqual(['alice', 'cara']);
  });

  it('rebuilds when a NEW document arrives', async () => {
    // The other half of the bound: proves the test above is not green merely because the index
    // is built once and then never updated.
    const {result, rerender, queryClient} = await ready();
    result.current.search('a');
    expect(vi.mocked(buildIndex)).toHaveBeenCalledTimes(1);

    vi.mocked(getUserDirectory).mockResolvedValue(directory(['dave']));
    await act(async () => {
      await queryClient.invalidateQueries();
    });
    rerender();
    await waitFor(() => expect(result.current.search('dave').map((r) => r.username)).toEqual(['dave']));

    expect(vi.mocked(buildIndex)).toHaveBeenCalledTimes(2);
  });

  it('caps the index and says so rather than quietly becoming slow', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const many = Array.from({length: MAX_INDEXED_USERNAMES + 3}, (_, n) => `user${String(n).padStart(6, '0')}`);
    vi.mocked(getUserDirectory).mockResolvedValue(directory(many));
    const {result} = await ready();

    result.current.search('user00');

    expect(warn.mock.calls[0][0]).toContain(String(MAX_INDEXED_USERNAMES));
  });

  it('does not warn about the cap for an ordinary directory', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const {result} = await ready();

    result.current.search('ali');

    expect(warn).not.toHaveBeenCalled();
  });
});
