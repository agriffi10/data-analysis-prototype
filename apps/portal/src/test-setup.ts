import '@testing-library/jest-dom';

// `expect.extend` registers `toHaveNoViolations` at runtime so every test can
// assert axe results without a per-file import; its TypeScript types are
// declared in `src/vitest-axe.d.ts`.
import {beforeEach, expect} from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';
import {memoryStorage} from './test/storage';

expect.extend(axeMatchers);

// jsdom has no `matchMedia`; the responsive hook (`useBreakpoint`, SPEC-095)
// needs it. Back it by `window.innerWidth` so a test can set the viewport width
// before render to drive breakpoint-gated mounts. Default jsdom width is 1024
// (≥ tablet, < desktop) → non-mobile, so existing tests keep desktop behavior.
if (typeof window.matchMedia !== 'function') {
  window.matchMedia = (query: string): MediaQueryList => {
    const min = Number(/\(min-width:\s*(\d+)px\)/.exec(query)?.[1] ?? 0);
    return {
      get matches() {
        return window.innerWidth >= min;
      },
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
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
// persisted UI prefs through the real hooks (e.g. the rail collapse state, SPEC-085) get
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
  try {
    globalThis.localStorage?.clear();
  } catch {
    // A spec that stubbed a throwing localStorage — nothing to clear.
  }
});
