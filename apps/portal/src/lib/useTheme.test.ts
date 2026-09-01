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

  it('agrees with the store on the key and the vocabulary it cannot import', () => {
    expect(initialiser).toContain(`'${THEME_STORAGE_KEY}'`);
    expect(initialiser).toContain("'(prefers-color-scheme: dark)'");
    expect(initialiser).toContain("setAttribute('data-theme'");
    expect(initialiser).toContain('colorScheme');
    // The same three-state vocabulary, read the same way.
    expect(initialiser).toContain("stored === 'light' || stored === 'dark' ? stored : 'system'");
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
