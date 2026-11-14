import {useCallback, useMemo} from 'react';
import {useParams as useRouteParams} from 'react-router';
import {useParams as useNextParams} from 'next/navigation';
import {useInCatchAll, useSeam} from './seamContext';
import type {NavigateOptions, NavigationType, NavLocation, To} from './navigation.types';

/** Where the user is: the address, the state its navigation carried, and the entry's key. */
export function useLocation(): NavLocation {
  return useSeam().location;
}

/** How the current entry was reached: a push, a replace, or a traversal (`'POP'`). */
export function useNavigationType(): NavigationType {
  return useSeam().navigationType;
}

/**
 * The seam's navigate: `navigate(to, {replace, state})`. It takes no history delta.
 *
 * While a router navigation is leaving the page, a replace on the same path corrects the address of
 * the entry left without re-rendering, so the navigation is not cancelled; a `Link` is the way to
 * let a click win over one in flight.
 */
export function useNavigate(): (to: To, options?: NavigateOptions) => void {
  return useSeam().navigate;
}

type NextSearch = URLSearchParams | ((previous: URLSearchParams) => URLSearchParams);

/**
 * The current query as `URLSearchParams`, and a setter that navigates to a new one on the same path,
 * as react-router's does (the hash is dropped).
 *
 * @returns The params and their setter.
 */
export function useSearchParams(): [URLSearchParams, (next: NextSearch, options?: NavigateOptions) => void] {
  const {location, navigate} = useSeam();
  const params = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const setParams = useCallback(
    (next: NextSearch, options?: NavigateOptions) => {
      const value = typeof next === 'function' ? next(new URLSearchParams(location.search)) : next;
      navigate(`?${value.toString()}`, options);
    },
    [location.search, navigate]
  );
  return [params, setParams];
}

/** A param as react-router hands it over: decoded, and never thrown on a malformed escape. */
function decodeParam(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * The current route's params, decoded.
 *
 * Inside the catch-all they are react-router's match; on a page the App Router serves they are
 * Next's, which arrive percent-encoded (measured: `a%40b%20c` for `a@b c`) and are decoded here so
 * a page reads the same value under either router. Both hooks are always called.
 *
 * @returns The params.
 */
export function useParams<T extends Record<string, string | undefined> = Record<string, string | undefined>>(): T {
  const inCatchAll = useInCatchAll();
  const routeParams = useRouteParams();
  const nextParams = useNextParams();
  return useMemo(() => {
    if (inCatchAll) return routeParams as T;
    const decoded: Record<string, string> = {};
    for (const [name, value] of Object.entries(nextParams ?? {})) {
      if (value === undefined) continue;
      decoded[name] = Array.isArray(value) ? value.map(decodeParam).join('/') : decodeParam(value);
    }
    return decoded as T;
  }, [inCatchAll, routeParams, nextParams]);
}
