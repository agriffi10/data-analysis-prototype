import {readFileSync} from 'node:fs';
import {act, renderHook} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {resetColorScheme, setPrefersDark} from '../test/colorScheme';
import {resetThemeForTest, THEME_STORAGE_KEY, useTheme} from './useTheme';

function mount() {
  resetThemeForTest();
  return renderHook(() => useTheme());
}

afterEach(() => {
  vi.restoreAllMocks();
  resetColorScheme();
  resetThemeForTest();
});

describe('the theme preference', () => {
  it('defaults to system, resolves it live, and remembers a choice', () => {
    const {result} = mount();
    expect(result.current.preference).toBe('system');
    expect(result.current.effective).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    // System re-resolves when the OS preference moves, with no reload.
    act(() => setPrefersDark(true));
    expect(result.current.effective).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');

    act(() => result.current.setPreference('light'));
    expect(result.current.effective).toBe('light');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');

    // …and an explicit choice does NOT re-resolve when the OS preference moves.
    act(() => setPrefersDark(false));
    act(() => setPrefersDark(true));
    expect(result.current.effective).toBe('light');
  });

  it('reads anything that is not light or dark as system', () => {
    // Including a value some earlier version wrote, and including junk: the stored string is
    // the one input here that nothing validates on the way in.
    for (const stored of ['auto', '', 'DARK', '{"theme":"dark"}']) {
      window.localStorage.setItem(THEME_STORAGE_KEY, stored);
      const {result, unmount} = mount();
      expect(result.current.preference, stored).toBe('system');
      unmount();
    }
  });

  it('still switches for the session when localStorage throws', () => {
    // Both the read and the write are wrapped: a private window that refuses storage must not
    // stop the app booting, and must not stop the control working either.
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('storage is disabled');
    });
    const setItem = vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('storage is disabled');
    });

    const {result} = mount();
    expect(result.current.preference).toBe('system');

    act(() => result.current.setPreference('dark'));
    expect(result.current.effective).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(setItem).toHaveBeenCalledWith(THEME_STORAGE_KEY, 'dark');
  });
});

describe('the pre-paint initialiser', () => {
  const initialiser = readFileSync('public/theme-init.js', 'utf8');
  const html = readFileSync('index.html', 'utf8');

  /**
   * Run the initialiser the way the browser does.
   *
   * It is RUN, not read for substrings. A substring check cannot tell a correct resolution from
   * an inverted one — swapping its two branches leaves every string it contains in place — and an
   * inverted resolution is exactly the flash of the wrong theme this file exists to prevent.
   * It is an ES5 IIFE with no imports, so executing it needs nothing but a document.
   */
  function runInitialiser(): void {
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.style.colorScheme = '';
    new Function(initialiser)();
  }

  it('resolves a stored choice, and resolves system through the OS', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    runInitialiser();
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');

    window.localStorage.setItem(THEME_STORAGE_KEY, 'light');
    setPrefersDark(true);
    runInitialiser();
    // An explicit choice wins over the OS — the inverted-branch mutation shows up right here.
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    window.localStorage.removeItem(THEME_STORAGE_KEY);
    runInitialiser();
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

    setPrefersDark(false);
    runInitialiser();
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('reads an unknown stored value as system, exactly as the store does', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'auto');
    setPrefersDark(true);
    runInitialiser();
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('throws on nothing, because it blocks the module script behind it', () => {
    // A failure here would stop the app booting, not just lose a preference. Both hazards: a
    // localStorage that throws on read, and a browser with no matchMedia at all.
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('storage is disabled');
    });
    expect(() => runInitialiser()).not.toThrow();
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    vi.restoreAllMocks();

    const matchMedia = window.matchMedia;
    // @ts-expect-error — deleting it is the case being reproduced.
    delete window.matchMedia;
    try {
      expect(() => runInitialiser()).not.toThrow();
      // …and it still PAINTS. Asserting only that nothing threw is satisfied by an initialiser
      // that reaches neither of its two writes: the outer catch swallows the TypeError, `<html>`
      // gets no attribute at all, and the page is unthemed until React mounts.
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
      expect(document.documentElement.style.colorScheme).toBe('light');
    } finally {
      window.matchMedia = matchMedia;
    }
  });

  it('agrees with the store on the key and the vocabulary it cannot import', () => {
    // The behaviour above is what matters; this pins the two literals a shared VALUE has to
    // agree on, which running the file cannot check because the store is not in its scope.
    expect(initialiser).toContain(`'${THEME_STORAGE_KEY}'`);
    expect(initialiser).toContain("'(prefers-color-scheme: dark)'");
  });

  it('is loaded blocking, in <head>, before the module script', () => {
    const initTag = html.indexOf('<script src="/theme-init.js"></script>');
    expect(initTag, 'index.html must load /theme-init.js').toBeGreaterThan(-1);
    expect(initTag).toBeLessThan(html.indexOf('</head>'));
    expect(initTag).toBeLessThan(html.indexOf('type="module"'));
    expect(html.slice(initTag, initTag + 60)).not.toMatch(/defer|async/);
  });

  it('carries no inline script anywhere, because the CSP has no nonce and no hash', () => {
    // `script-src 'self'` with neither a nonce nor a hash: an inline initialiser would run in
    // dev and be refused in production, which is the worst shape of failure available.
    const inline = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)];
    expect(inline.map((match) => match[1].trim()).filter(Boolean)).toEqual([]);
  });
});
