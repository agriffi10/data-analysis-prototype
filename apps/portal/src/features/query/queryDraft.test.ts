import {
  describe,
  it,
  expect,
  beforeEach,
  afterEach,
  vi,
} from 'vitest';
import { readQueryDraft, writeQueryDraft, clearQueryDraft } from './queryDraft';
import { QUERY_DRAFT_STORAGE_PREFIX } from './query.constants';

describe('queryDraft', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('writes and reads a draft under the per-user key', () => {
    writeQueryDraft('alice', 'SELECT 1;');
    expect(sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`)).toBe(
      'SELECT 1;',
    );
    expect(readQueryDraft('alice')).toBe('SELECT 1;');
  });

  it('keys drafts per-user so one user never sees another', () => {
    writeQueryDraft('alice', 'SELECT alice;');
    writeQueryDraft('bob', 'SELECT bob;');
    expect(readQueryDraft('alice')).toBe('SELECT alice;');
    expect(readQueryDraft('bob')).toBe('SELECT bob;');
  });

  it('returns null when no draft exists for the user', () => {
    expect(readQueryDraft('alice')).toBeNull();
  });

  it('clear removes the draft', () => {
    writeQueryDraft('alice', 'SELECT 1;');
    clearQueryDraft('alice');
    expect(readQueryDraft('alice')).toBeNull();
  });

  it('is a no-op for an empty username (unauthenticated dev paths)', () => {
    writeQueryDraft('', 'SELECT 1;');
    expect(sessionStorage.length).toBe(0);
    expect(readQueryDraft('')).toBeNull();
    // Should not throw.
    clearQueryDraft('');
  });

  it('swallows storage failures rather than throwing', () => {
    const setItem = vi.fn(() => {
      throw new Error('QuotaExceededError');
    });
    const getItem = vi.fn(() => {
      throw new Error('SecurityError');
    });
    const removeItem = vi.fn(() => {
      throw new Error('SecurityError');
    });
    vi.stubGlobal('sessionStorage', { setItem, getItem, removeItem });

    expect(() => writeQueryDraft('alice', 'SELECT 1;')).not.toThrow();
    expect(readQueryDraft('alice')).toBeNull();
    expect(() => clearQueryDraft('alice')).not.toThrow();

    expect(setItem).toHaveBeenCalled();
    expect(getItem).toHaveBeenCalled();
    expect(removeItem).toHaveBeenCalled();
  });
});
