import {useCallback, useMemo} from 'react';
import {useParams as useNextParams} from 'next/navigation';
import {committedAddress} from './address';
import {useSeam} from './seamContext';
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
      // From the committed search, which a page that is leaving has corrected without re-rendering.
      const value = typeof next === 'function' ? next(new URLSearchParams(committedAddress().search)) : next;
      navigate(`?${value.toString()}`, options);
    },
    [navigate]
  );
  return [params, setParams];
}

/** A param decoded once, and never thrown on a malformed escape. */
function decodeParam(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * The current page's params, decoded once.
 *
 * Next hands them over percent-encoded (measured: `a%40b%20c` for `a@b c`), from the page the router
 * last rendered rather than the address, so a native navigation leaves them as they were.
 *
 * @returns The params.
 */
export function useParams<T extends Record<string, string | undefined> = Record<string, string | undefined>>(): T {
  const nextParams = useNextParams();
  return useMemo(() => {
    const decoded: Record<string, string> = {};
    for (const [name, value] of Object.entries(nextParams ?? {})) {
      if (value === undefined) continue;
      decoded[name] = Array.isArray(value) ? value.map(decodeParam).join('/') : decodeParam(value);
    }
    return decoded as T;
  }, [nextParams]);
}
