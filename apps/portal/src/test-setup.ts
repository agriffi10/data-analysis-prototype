import '@testing-library/jest-dom';

// `expect.extend` registers `toHaveNoViolations` at runtime so every test can
// assert axe results without a per-file import; its TypeScript types are
// declared in `src/vitest-axe.d.ts`.
import {beforeEach, expect} from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';
import {memoryStorage} from './test/storage';
import {addSchemeListener, prefersDarkScheme, removeSchemeListener, resetColorScheme} from './test/colorScheme';

expect.extend(axeMatchers);

// jsdom has no `matchMedia`, and two things need it: the responsive hook
// (`useBreakpoint`) and the theme store's OS preference. Width queries are backed by
// `window.innerWidth`, so a test can set the viewport before render to drive
// breakpoint-gated mounts — default jsdom width is 1024 (≥ tablet, < desktop) → non-mobile,
// so existing tests keep desktop behavior. `prefers-color-scheme` is backed by
// `test/colorScheme.ts`, which a test drives with `setPrefersDark`.
//
// Anything else answers FALSE. It used to answer `innerWidth >= 0`, i.e. true, for every
// query that was not a width — so the day a second kind of query arrived it would have been
// matched by accident, and the whole suite would have run in the dark theme with nothing
// saying so.
if (typeof window.matchMedia !== 'function') {
  window.matchMedia = (query: string): MediaQueryList => {
    const width = /\(min-width:\s*(\d+)px\)/.exec(query);
    const scheme = /\(prefers-color-scheme:\s*(dark|light)\)/.exec(query);
    return {
      get matches() {
        if (width) return window.innerWidth >= Number(width[1]);
        if (scheme) return (scheme[1] === 'dark') === prefersDarkScheme();
        return false;
      },
      media: query,
      onchange: null,
      addEventListener(_type: string, listener: (event: MediaQueryListEvent) => void) {
        if (scheme) addSchemeListener(listener);
      },
      removeEventListener(_type: string, listener: (event: MediaQueryListEvent) => void) {
        if (scheme) removeSchemeListener(listener);
      },
      addListener() {},
      removeListener() {},
      dispatchEvent() {
        return false;
      }
    } as unknown as MediaQueryList;
  };
}

// Baseline working `localStorage` for every test (Node's experimental one is broken
// here). Defined ONCE (redefining the global property before every test can destabilise
// the jsdom global proxy), then cleared before each test so page-level specs that read
// persisted UI prefs through the real hooks (e.g. the rail collapse state) get
// a clean, functional store; prefs specs that assert persistence stub their own via
// `vi.stubGlobal`. sessionStorage is jsdom's and left alone.
const baselineLocalStorage = memoryStorage();
try {
  Object.defineProperty(globalThis, 'localStorage', {
    value: baselineLocalStorage,
    writable: true,
    configurable: true
  });
} catch {
  (globalThis as {localStorage: Storage}).localStorage = baselineLocalStorage;
}

beforeEach(() => {
  resetColorScheme();
  try {
    globalThis.localStorage?.clear();
  } catch {
    // A spec that stubbed a throwing localStorage — nothing to clear.
  }
});
