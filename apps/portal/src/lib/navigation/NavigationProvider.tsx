'use client';
import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {usePathname, useRouter, useSearchParams} from 'next/navigation';
import {routerFor, useAreaRecords} from './areas';
import {
  KEY_FIELD,
  committedAddress,
  hrefOf,
  isRefusedTarget,
  keyOf,
  newKey,
  normalizePathname,
  resolveTo,
  sameDocument,
  type Address
} from './address';
import {SeamContext, type Seam} from './seamContext';
import type {NavigateOptions, NavigationType, NavLocation, To} from './navigation.types';

/** A history entry as the seam knows it: the location, and how it was reached. */
type Entry = NavLocation & {type: NavigationType};

/** A navigation the seam started and has not seen render: written natively, or handed to Next's router. */
type Expected = Entry & {native: boolean};

/** The entry a router navigation left, and the address it left from. */
type Leave = {from: Entry; at: string};

/** Next's own fields on a history entry, which the seam copies onto an in-page anchor's. */
type NextHistoryState = {__NA?: unknown; __PRIVATE_NEXTJS_INTERNALS_TREE?: unknown};

/**
 * The navigation seam's one adapter: Next's pathname and search are the address, and the seam owns
 * what the App Router lacks — the navigation type, a key per history entry, the hash, and the state
 * a navigation carries.
 *
 * WHICH ROUTER PERFORMS A NAVIGATION. The source is the committed address, `window.location`, never
 * this component's latest render, which can be a transition Next has not committed. A target that
 * keeps the committed path, or one whose source and target the catch-all both serve, is written
 * with `history.pushState`/`replaceState`: Next copies its own state into the entry and moves
 * `usePathname` and `useSearchParams` without rendering a new segment, so the page stays mounted
 * and nothing is fetched. Every other navigation is Next's `router.push`/`replace`.
 *
 * HOW A CHANGE IS CLASSIFIED, while rendering. A change the seam started is what its call said. One
 * it did not start, with the address already moved, is a traversal (`'POP'`): Next writes the
 * address of its own navigations only after rendering them, and React renders a traversal inside
 * Next's popstate dispatch, before any listener added here could say so. A popstate listener
 * covers only the traversal that leaves the path and search unchanged, an in-page anchor.
 *
 * A PAGE THAT IS LEAVING. While a router navigation waits on the server, the page it left stays
 * mounted, and a native write would make Next restore and discard that navigation, losing the
 * click. So a page's own replace on the same path, how a page corrects its address, is written onto
 * the entry it left with Next's state, which Next passes through; the page does not re-render with
 * it. A link (`follow`), a push, or another page is the user leaving again, and the last click wins.
 *
 * STATE AND KEYS. State lives only in this component's memory, for the entry the navigation made,
 * so a reload or a traversal delivers none. Every push or replace gets a fresh key, written onto
 * the entry beside Next's own state, so a traversal back reads it again; an entry with none reads
 * as `'default'`.
 *
 * @param props.children - The app.
 * @param props.initialState - The first entry's state, seeded before anything below mounts; only
 *   the test harness passes it.
 * @returns The seam's provider.
 */
export function NavigationProvider({children, initialState}: {children: ReactNode; initialState?: unknown}) {
  const pathname = usePathname();
  const nextSearch = useSearchParams();
  const router = useRouter();
  const records = useAreaRecords();
  const searchString = nextSearch.toString();
  const rendered: Address = {pathname, search: searchString ? `?${searchString}` : '', hash: ''};

  const [entry, setEntry] = useState<Entry>(() => ({
    ...committedAddress(),
    state: initialState,
    key: keyOf(window.history.state),
    type: 'POP'
  }));
  const [expected, setExpected] = useState<Expected | null>(null);
  const entryRef = useRef(entry);
  const leaving = useRef<Leave | null>(null);
  const lastNextState = useRef<NextHistoryState | null>(null);

  let current = entry;
  if (!sameDocument(entry, rendered)) {
    const at = committedAddress();
    // An expectation is what renders only while it can be: a native one has written its own entry,
    // and a router one renders before Next writes the address. A router push Next dropped for a
    // traversal to the same address is neither, and taking it would call the Back a push.
    const arrived =
      expected !== null &&
      sameDocument(expected, rendered) &&
      (expected.native ? keyOf(window.history.state) === expected.key : !sameDocument(at, rendered));
    if (arrived) {
      current = {
        pathname: expected.pathname,
        search: expected.search,
        hash: expected.hash,
        state: expected.state,
        key: expected.key,
        type: expected.type
      };
      setExpected(null);
    } else if (sameDocument(at, rendered)) {
      // An expectation left here is not cleared: one for another address may be a router navigation
      // still to render, and one for this address can no longer arrive, by the rule above.
      current = {...at, state: undefined, key: keyOf(window.history.state), type: 'POP'};
    } else {
      current = {...rendered, state: undefined, key: newKey(), type: 'PUSH'};
    }
    setEntry(current);
  }

  useLayoutEffect(() => {
    entryRef.current = entry;
  }, [entry]);

  // The key goes onto the entry once the address is written, beside Next's state. A native
  // navigation wrote it already; a router one did not, and Next keeps `__NA` on what it wrote, so
  // this write passes through Next's history patch untouched.
  useEffect(() => {
    if (entry.type === 'POP' || !sameDocument(committedAddress(), entry)) return;
    const state = window.history.state as Record<string, unknown> | null;
    if (state?.[KEY_FIELD] === entry.key) return;
    window.history.replaceState({...state, [KEY_FIELD]: entry.key}, '');
  }, [entry]);

  // The Next state last seen on this page, for making an in-page anchor's entry restorable.
  useEffect(() => {
    const state = window.history.state as NextHistoryState | null;
    if (state?.__NA) {
      lastNextState.current = {
        __NA: state.__NA,
        __PRIVATE_NEXTJS_INTERNALS_TREE: state.__PRIVATE_NEXTJS_INTERNALS_TREE
      };
    }
  });

  useEffect(() => {
    const onPopState = (event: PopStateEvent) => {
      const at = committedAddress();
      const now = entryRef.current;
      if (!sameDocument(at, now)) return;
      // An in-page anchor makes an entry with no state, and Next ignores a popstate whose state is
      // null, so a later Back onto this entry would leave the page it came from on screen. Stamped
      // with the Next state of the page it belongs to, it is one Next restores.
      if (event.state == null && lastNextState.current) {
        window.history.replaceState({...lastNextState.current}, '');
      }
      const key = keyOf(event.state);
      if (now.type === 'POP' && now.key === key && now.hash === at.hash) return;
      setEntry({...at, state: undefined, key, type: 'POP'});
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const go = useCallback(
    (to: To, options: NavigateOptions, clicked: boolean) => {
      const from = committedAddress();
      if (isRefusedTarget(to, from)) {
        console.warn('[navigation] refused a navigation to a target outside the portal');
        return;
      }
      const target = resolveTo(to, from);
      const type: NavigationType = options.replace ? 'REPLACE' : 'PUSH';
      const next: Entry = {...target, state: options.state, key: newKey(), type};
      const href = hrefOf(target);
      const native =
        target.pathname === normalizePathname(from.pathname) ||
        (routerFor(from.pathname, records) === 'catch-all' && routerFor(target.pathname, records) === 'catch-all');
      if (!native) {
        leaving.current = {from: entryRef.current, at: hrefOf(from)};
        setExpected({...next, native: false});
        if (type === 'PUSH') router.push(href);
        else router.replace(href);
        return;
      }
      const left = leaving.current;
      if (
        left !== null &&
        !clicked &&
        type === 'REPLACE' &&
        target.pathname === normalizePathname(from.pathname) &&
        left.from === entryRef.current &&
        left.at === hrefOf(from)
      ) {
        // Carrying Next's own state, the write passes through Next untouched, so the navigation in
        // flight is not restored away, and Back to this entry finds the corrected address.
        const state = window.history.state as NextHistoryState | null;
        const data = state?.__NA ? state : lastNextState.current && {...state, ...lastNextState.current};
        if (data) {
          window.history.replaceState(data, '', href);
          leaving.current = {...left, at: href};
        }
        return;
      }
      // Next re-renders only when its path or search moves; when neither does, nothing would.
      if (sameDocument(target, entryRef.current)) setEntry(next);
      else setExpected({...next, native: true});
      const data = {[KEY_FIELD]: next.key};
      if (type === 'PUSH') window.history.pushState(data, '', href);
      else window.history.replaceState(data, '', href);
    },
    [records, router, setEntry, setExpected]
  );

  const navigate = useCallback((to: To, options: NavigateOptions = {}) => go(to, options, false), [go]);
  const follow = useCallback((to: To, options: NavigateOptions = {}) => go(to, options, true), [go]);

  const value = useMemo<Seam>(() => {
    const {type, ...location} = current;
    return {location, navigationType: type, navigate, follow};
  }, [current, navigate, follow]);

  return <SeamContext.Provider value={value}>{children}</SeamContext.Provider>;
}
