import '@testing-library/jest-dom/vitest';

// `expect.extend` registers `toHaveNoViolations` at runtime so every test can
// assert axe results without a per-file import; its TypeScript types are
// declared in `src/vitest-axe.d.ts`.
import {afterAll, beforeEach, expect, onTestFinished, vi} from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';
import {notifyManager} from '@tanstack/query-core';
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

/**
 * `setTimeout` as it stood before any test could install a fake clock.
 *
 * The drain below has to be a REAL macrotask. A test that leaves `vi.useFakeTimers()` installed
 * would otherwise park the hook on a clock nothing ever advances, and it would fail on its own
 * timeout instead of draining. Nothing is lost by stepping around the fake clock: a fake timer
 * still pending when `vi.useRealTimers()` runs is discarded and never fires at all, so it can
 * never reach a torn-down environment either way.
 *
 * Captured per FILE, which is safe only because `isolate` is on — each file re-evaluates this
 * module in a fresh environment before any test can touch the clock. Turning isolation off
 * would let one file's leftover fake clock become the next file's capture, and the hook would
 * then hang while blaming a file that did nothing wrong.
 */
const realSetTimeout = globalThis.setTimeout.bind(globalThis);

/**
 * Notifications TanStack has scheduled on the real clock and not yet delivered.
 *
 * Counted here because nothing else can see them, and both the drain and the check below need
 * the number: the drain to know whether it still has work, the check to refuse a file that
 * reaches teardown with work left. Callbacks scheduled while a fake clock is installed are
 * deliberately NOT counted — `vi.useRealTimers()` discards those rather than firing them, so
 * they can neither reach a dead environment nor ever bring this count back down.
 *
 * The wrapper calls the AMBIENT `setTimeout`, exactly as query-core's own scheduler does, so a
 * notification's timing is unchanged by being counted. Using the captured real one would move
 * fake-clock notifications onto the real clock and change what the suite exercises.
 */
let realPending = 0;
notifyManager.setScheduler((callback: () => void) => {
  const onFakeClock = vi.isFakeTimers();
  if (!onFakeClock) realPending += 1;
  setTimeout(() => {
    if (!onFakeClock) realPending -= 1;
    callback();
  }, 0);
});

/** Enough turns for a notification chain to settle; a runaway one fails the check instead. */
const MAX_DRAIN_TURNS = 10;

/**
 * Let TanStack's queued notifications run before this file's jsdom is taken away.
 *
 * TanStack batches every notification through a `setTimeout(0)`. A batch still queued when
 * vitest tears down the environment fires into a world with no `window`, and react-dom reads
 * `window.event` unconditionally when an update is scheduled — an uncaught `ReferenceError`
 * that fails a run whose every test passed, blaming whichever file was last. Yielding real
 * macrotasks after each test empties the queue while the environment is still standing.
 *
 * A LOOP rather than a single yield, because delivering one notification can schedule the next:
 * one turn drains one generation, and the generation it uncovers would be left behind.
 *
 * Registered HERE rather than in `renderWithProviders`, and that placement is the point: the
 * queue belongs to the worker, not to any one client, so a test that builds its own
 * `QueryClientProvider` needs draining just as much as one that goes through the harness — and
 * some do, with a client created at module scope where a per-render hook could never reach it.
 * `onTestFinished` runs after every `afterEach`, so this lands once Testing Library has
 * unmounted; registered from `beforeEach`, it is also the FIRST such hook, and they run in
 * reverse, so the harness's own cache teardown still goes before this drain.
 */
beforeEach(() => {
  onTestFinished(async () => {
    for (let turn = 0; realPending > 0 && turn < MAX_DRAIN_TURNS; turn += 1) {
      await new Promise((resolve) => realSetTimeout(resolve, 0));
    }
  });
});

/**
 * Refuse a file that reaches teardown with a notification still queued.
 *
 * Without this the drain is a guard nothing watches: delete it and the suite stays green, every
 * test passing, until the race resurfaces as an intermittent `ReferenceError` in whichever file
 * was unlucky. Asserting the count here turns that into a deterministic failure in the file that
 * actually leaked, on every run rather than one in three.
 */
afterAll(() => {
  expect(
    realPending,
    'a TanStack notification was still queued when this file finished — it would fire after the environment is torn down'
  ).toBe(0);
});
