import '@testing-library/jest-dom';

// `expect.extend` registers `toHaveNoViolations` at runtime so every test can
// assert axe results without a per-file import; its TypeScript types are
// declared in `src/vitest-axe.d.ts`.
import {beforeEach, expect} from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';
import {memoryStorage} from './test/storage';

expect.extend(axeMatchers);

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
