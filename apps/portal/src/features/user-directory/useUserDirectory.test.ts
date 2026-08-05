import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {unauthenticated} from '../../test/authFixtures';
import {useUserDirectory} from './useUserDirectory';
import {getUserDirectory} from './userDirectory.service';
import {MAX_INDEXED_USERNAMES} from './usernameTrie';

vi.mock('./userDirectory.service', () => ({getUserDirectory: vi.fn()}));

const directory = (usernames: string[], generatedAt = '2026-08-05T04:00:11Z') => ({
  success: true as const,
  data: {usernames, generatedAt}
});

beforeEach(() => {
  vi.clearAllMocks();
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

  it('builds the index once, however many times it is searched', async () => {
    // The index is built on the first call and memoised behind the callback. Rebuilding it per
    // keystroke would be invisible in a small directory and ruinous in a large one, so the
    // guard is a cost assertion rather than an output one.
    const {result, rerender} = await ready();

    const started = performance.now();
    for (let n = 0; n < 500; n += 1) {
      result.current.search('a');
      rerender();
    }
    expect(performance.now() - started).toBeLessThan(2000);
    expect(result.current.search('a').map((r) => r.username)).toEqual(['alice', 'cara']);
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
