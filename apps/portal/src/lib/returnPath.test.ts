import {describe, it, expect, beforeEach, afterEach, vi} from 'vitest';
import {setReturnPath, setReturnPathIfAbsent, takeReturnPath} from './returnPath';

const KEY = 'portal.returnPath';

beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('returnPath', () => {
  it('stores a path with setReturnPath and reads it back once', () => {
    setReturnPath('/query');
    expect(sessionStorage.getItem(KEY)).toBe('/query');
    expect(takeReturnPath()).toBe('/query');
    // takeReturnPath clears — a second read is null.
    expect(takeReturnPath()).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it('takeReturnPath returns null when nothing is stored', () => {
    expect(takeReturnPath()).toBeNull();
  });

  it('setReturnPathIfAbsent stores only when no path is present', () => {
    setReturnPathIfAbsent('/files');
    expect(sessionStorage.getItem(KEY)).toBe('/files');
  });

  it('setReturnPathIfAbsent does not clobber an already-stored path', () => {
    setReturnPath('/query/tab-1'); // a specific protected path captured by the gate
    setReturnPathIfAbsent('/files'); // default sign-in destination — must not win
    expect(sessionStorage.getItem(KEY)).toBe('/query/tab-1');
  });

  it('setReturnPath swallows a storage failure (private browsing)', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceeded');
    });
    expect(() => setReturnPath('/query')).not.toThrow();
  });

  it('takeReturnPath returns null when storage access throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    expect(takeReturnPath()).toBeNull();
  });
});
