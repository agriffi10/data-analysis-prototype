import {useInsertionEffect, useMemo, useSyncExternalStore, type ReactNode} from 'react';
import {flushSync} from 'react-dom';
import {act} from '@testing-library/react';

/**
 * Vitest's `next/navigation`: Next's App Router modelled on jsdom's own history, so the navigation
 * seam runs in tests against the same behaviours it rests on in the browser.
 *
 * Aliased in `vite.config.ts`, so nothing imports this file by its path except the harness. Each of
 * the eight behaviours below was measured on Next 16.4.6 and has a test of its own in
 * `nextNavigation.test.tsx`:
 *
 * 1. A router push or replace renders before it writes the address (the write is an insertion
 *    effect in `NextStandInRoot`, as Next's `HistoryUpdater`).
 * 2. A traversal renders with the address already moved, inside the popstate dispatch, before any
 *    listener the app adds (a capture-phase listener registered first, rendering with `flushSync`).
 * 3. An external `pushState`/`replaceState` moves the pathname and search without changing the
 *    page, and copies Next's state from the current entry into the new one; a call whose data
 *    carries `__NA` passes through untouched.
 * 4. A popstate whose state is null is ignored (and one without `__NA` would reload the document,
 *    which is recorded rather than performed).
 * 5. `useSearchParams` re-serializes the search (`%20` reads back as `+`).
 * 6. A router push or replace fetches the page, recorded in `requests()`, and a push to the
 *    current address replaces the entry rather than adding one.
 * 7. A router push can stay uncommitted while the user clicks again (`hold()`): a later router
 *    navigation supersedes it, and an external `pushState` or a traversal drops it, the first moving
 *    the address over the page already shown.
 *
 * A router navigation to another origin is a document navigation that leaves the portal; it is
 * recorded in `external()` and changes nothing here.
 * 8. `useParams` returns the selected page's params percent-encoded, from the page the router last
 *    navigated to, not from the address.
 */

/** The page selection: the href the router last navigated to. A native navigation does not move it. */
type Tree = {href: string};

/** A history write the root performs after the render that needs it, as Next's `HistoryUpdater`. */
type Write = {kind: 'push' | 'replace' | 'preserve'; href: string};

type RouterState = {url: string; tree: Tree; write: Write | null};

type Navigation = {url: string; hash: string; kind: 'push' | 'replace'};

type PageResolver = (pathname: string) => {params: Record<string, string | string[]>} | null;

type StandIn = {
  state: RouterState;
  listeners: Set<() => void>;
  requests: string[];
  external: string[];
  reloads: number;
  holding: boolean;
  parked: Navigation | null;
  resolver: PageResolver | null;
  originalPush: History['pushState'];
  originalReplace: History['replaceState'];
};

const NEXT_FIELDS = ['__NA', '__PRIVATE_NEXTJS_INTERNALS_TREE'] as const;

/** Writes already performed, so a re-render of the same state never writes twice. */
const performed = new WeakSet<Write>();

const currentHref = () => window.location.pathname + window.location.search + window.location.hash;
const urlOf = (href: string) => {
  const parsed = new URL(href, window.location.href);
  return {url: parsed.pathname + parsed.search, hash: parsed.hash};
};

/**
 * One stand-in per jsdom window, kept on the window so a module re-evaluated by `vi.resetModules`
 * shares the same history patch, listener and state rather than installing a second set.
 */
function standIn(): StandIn {
  const holder = window as unknown as {__nextStandIn?: StandIn};
  holder.__nextStandIn ??= install();
  return holder.__nextStandIn;
}

function install(): StandIn {
  const instance: StandIn = {
    state: {
      url: window.location.pathname + window.location.search,
      tree: {href: window.location.pathname + window.location.search},
      write: null
    },
    listeners: new Set(),
    requests: [],
    external: [],
    reloads: 0,
    holding: false,
    parked: null,
    resolver: null,
    originalPush: window.history.pushState.bind(window.history),
    originalReplace: window.history.replaceState.bind(window.history)
  };

  // Behaviour 3: Next's history patch.
  const patched =
    (original: History['pushState']) =>
    (data: unknown, unused: string, url?: string | URL | null): void => {
      const fields = data as Record<string, unknown> | null | undefined;
      if (fields?.__NA || fields?._N) {
        original(data, unused, url);
        return;
      }
      const copied: Record<string, unknown> = {...(fields ?? {})};
      const current = window.history.state as Record<string, unknown> | null;
      for (const field of NEXT_FIELDS) if (current?.[field]) copied[field] = current[field];
      if (url != null) {
        // Next drops a navigation still in flight when the address moves under it, and restores the
        // tree it already shows at the new address.
        instance.parked = null;
        const moved = urlOf(String(url));
        setState(instance, {
          url: moved.url,
          tree: instance.state.tree,
          write: {kind: 'preserve', href: moved.url + moved.hash}
        });
      }
      original(copied, unused, url);
    };
  window.history.pushState = patched(instance.originalPush);
  window.history.replaceState = patched(instance.originalReplace);

  // Behaviours 2 and 4: registered before anything the app adds, in the capture phase, and
  // rendering inside the dispatch.
  window.addEventListener(
    'popstate',
    (event: PopStateEvent) => {
      const data = event.state as Record<string, unknown> | null;
      if (data == null) return;
      if (!data.__NA) {
        instance.reloads += 1;
        return;
      }
      // A traversal takes priority over a navigation still in flight, which Next drops.
      instance.parked = null;
      const tree = (data.__PRIVATE_NEXTJS_INTERNALS_TREE as Tree | undefined) ?? instance.state.tree;
      const href = currentHref();
      flushSync(() =>
        setState(instance, {
          url: window.location.pathname + window.location.search,
          tree,
          write: {kind: 'preserve', href}
        })
      );
    },
    true
  );
  return instance;
}

function setState(instance: StandIn, next: RouterState): void {
  instance.state = next;
  for (const listener of instance.listeners) listener();
}

function subscribe(listener: () => void): () => void {
  const instance = standIn();
  instance.listeners.add(listener);
  return () => instance.listeners.delete(listener);
}

/** Behaviour 6 and 7: a router navigation, recorded, then committed or parked. */
function routerNavigate(href: string, mode: 'push' | 'replace'): void {
  const instance = standIn();
  if (new URL(href, window.location.href).origin !== window.location.origin) {
    instance.external.push(href);
    return;
  }
  const {url, hash} = urlOf(href);
  instance.requests.push(url);
  const navigation: Navigation = {url, hash, kind: mode};
  if (instance.holding) {
    instance.holding = false;
    instance.parked = navigation;
    return;
  }
  instance.parked = null;
  commit(instance, navigation);
}

function commit(instance: StandIn, navigation: Navigation): void {
  setState(instance, {
    url: navigation.url,
    tree: {href: navigation.url},
    write: {kind: navigation.kind, href: navigation.url + navigation.hash}
  });
}

const ROUTER = {
  push: (href: string) => routerNavigate(href, 'push'),
  replace: (href: string) => routerNavigate(href, 'replace'),
  back: () => window.history.back(),
  forward: () => window.history.forward(),
  refresh: () => undefined,
  prefetch: () => undefined
};

const pathOf = (url: string) => {
  const queryAt = url.indexOf('?');
  return queryAt < 0 ? url : url.slice(0, queryAt);
};
const searchOf = (url: string) => {
  const queryAt = url.indexOf('?');
  return queryAt < 0 ? '' : url.slice(queryAt);
};

/** Next's `usePathname`. */
export function usePathname(): string {
  return useSyncExternalStore(subscribe, () => pathOf(standIn().state.url));
}

/** Next's `useSearchParams`, re-serializing as Next's does (behaviour 5). */
export function useSearchParams(): URLSearchParams {
  const search = useSyncExternalStore(subscribe, () => searchOf(standIn().state.url));
  return useMemo(() => new URLSearchParams(search), [search]);
}

/** Next's `useRouter`. */
export function useRouter(): typeof ROUTER {
  return ROUTER;
}

/** Next's `useParams`: the selected page's params, percent-encoded (behaviour 8). */
export function useParams(): Record<string, string | string[]> {
  const tree = useSyncExternalStore(subscribe, () => standIn().state.tree);
  return useMemo(() => standIn().resolver?.(pathOf(tree.href))?.params ?? {}, [tree]);
}

/** The href the router last navigated to, which is what selects the page. */
export function useStandInTree(): string {
  return useSyncExternalStore(subscribe, () => standIn().state.tree.href);
}

/**
 * The stand-in's root, which both harness entry points mount: it performs each history write after
 * the commit that rendered it, in an insertion effect, as Next's `HistoryUpdater` does (behaviour 1).
 * A router push replaces the entry's state with Next's alone; a restore or a traversal keeps what
 * the entry already carries.
 */
export function NextStandInRoot({children}: {children: ReactNode}) {
  const state = useSyncExternalStore(subscribe, () => standIn().state);
  useInsertionEffect(() => {
    const write = state.write;
    if (!write || performed.has(write)) return;
    performed.add(write);
    const instance = standIn();
    const next = {__NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: state.tree};
    if (write.kind === 'push' && currentHref() !== write.href) instance.originalPush(next, '', write.href);
    else if (write.kind === 'preserve')
      instance.originalReplace({...(window.history.state ?? {}), ...next}, '', write.href);
    else instance.originalReplace(next, '', write.href);
  }, [state]);
  return children;
}

/**
 * Start a test at the address jsdom's history already shows, as a fresh page load: the router's
 * page is that address, nothing is parked or recorded, and the entry gets Next's state as Next's
 * first render writes it.
 *
 * @param resolver - How a path selects a page and its params; `renderApp` passes its own.
 */
export function resetStandIn(resolver: PageResolver | null = null): void {
  const instance = standIn();
  const url = window.location.pathname + window.location.search;
  instance.requests = [];
  instance.external = [];
  instance.reloads = 0;
  instance.holding = false;
  instance.parked = null;
  instance.resolver = resolver;
  instance.state = {url, tree: {href: url}, write: null};
  instance.originalReplace(
    {...(window.history.state ?? {}), __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: instance.state.tree},
    '',
    currentHref()
  );
}

/** Write to jsdom's history without Next's patch: the harness's own address setup and restore. */
export function writeAddressRaw(state: unknown, href: string): void {
  standIn().originalReplace(state, '', href);
}

/** The router navigations made since the reset, by path and query: the pages Next would have fetched. */
export function requests(): readonly string[] {
  return [...standIn().requests];
}

/** The router navigations that would have left the portal for another origin. */
export function external(): readonly string[] {
  return [...standIn().external];
}

/** How many popstates Next would have answered by reloading the document. */
export function reloads(): number {
  return standIn().reloads;
}

/** Park the next router navigation uncommitted, as a slow fetch leaves it (behaviour 7). */
export function hold(): void {
  standIn().holding = true;
}

/** Commit the navigation `hold` parked, if nothing superseded or dropped it. */
export function release(): void {
  const instance = standIn();
  const parked = instance.parked;
  instance.parked = null;
  instance.holding = false;
  if (parked) act(() => commit(instance, parked));
}

/** A promise for the next popstate, settled after every listener on the window has run. */
export function nextPopstate(): Promise<PopStateEvent> {
  return new Promise((resolve) =>
    window.addEventListener('popstate', (event) => setTimeout(() => resolve(event), 0), {once: true})
  );
}

/**
 * Go back or forward through jsdom's history, inside `act`, and wait for the traversal to land.
 *
 * @param delta - `-1` for Back, `1` for Forward.
 */
export async function traverse(delta: number): Promise<void> {
  await act(async () => {
    const landed = nextPopstate();
    window.history.go(delta);
    await landed;
  });
}
