import {StrictMode, useLayoutEffect, useState} from 'react';
import {onTestFinished} from 'vitest';
import {render, renderHook} from '@testing-library/react';
import type {RenderOptions, RenderHookOptions} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type {UserEvent} from '@testing-library/user-event';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {Route, Routes} from 'react-router';
import type {ReactElement, ReactNode} from 'react';
import {
  AreaRecordsContext,
  CatchAllRouter,
  NavigationProvider,
  useLocation,
  type AreaRecord,
  type NavLocation
} from '../lib/navigation';
import {NextStandInRoot, resetStandIn, writeAddressRaw} from './nextNavigation';
import {AuthContext} from '../features/auth/authContext';
import type {AuthContextValue} from '../features/auth/auth.types';
import {ToastProvider} from '../components/ToastProvider';
import {authValue} from './authFixtures';
import {FEATURE_FLAG_DEFAULTS, featureFlagKeys} from '../features/feature-flags';
import type {FeatureFlags} from '../features/feature-flags';
import {configValue} from '../lib/runtimeConfig';

/**
 * QueryClient for tests: retries off (a mocked service rejection should fail the
 * assertion immediately, not after a backoff) and no caching between renders
 * (`staleTime`/`gcTime` 0) so each test starts from a cold cache. Prefer the
 * shared instance via `renderWithProviders`; construct one directly only when a
 * test needs to inspect the cache.
 *
 * `retryDelay: 0` matters only to a hook that sets its own `retry`: that retry still
 * fires, and fires at once, rather than after TanStack's one-second backoff, which is
 * exactly as long as `waitFor`'s window.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {retry: false, retryDelay: 0, staleTime: 0, gcTime: 0},
      mutations: {retry: false}
    }
  });
}

/**
 * Drop the cache on `client` once the test that adopted it finishes.
 *
 * `onTestFinished` runs after every `afterEach`, so this lands once Testing Library has already
 * unmounted the tree — the only point where tearing the cache down is both safe and complete.
 *
 * `clear()` destroys every query, and destroying one cancels its in-flight fetch, so a request
 * the test never waited for cannot settle into an environment that is on its way out. Tests DO
 * end that way: to count them, filter this client's cache for `fetchStatus === 'fetching'` here
 * before clearing. `cancelQueries()` is deliberately not called first — `clear()` already
 * cancels, silently, and a second cancel only schedules more notifications.
 *
 * What this does NOT do is fix the teardown flake TanStack's batched notifications cause; that
 * needs a drain every test gets, harness or not, and it lives in `src/test-setup.ts`.
 */
function clearAfterTest(client: QueryClient): void {
  onTestFinished(() => {
    client.clear();
  });
}

/**
 * `delay: null` types the whole string in one go instead of yielding a macrotask per
 * keystroke — the default `delay: 0` costs a real event-loop turn per character, which
 * is pure overhead in a jsdom suite with no debounce to exercise. A test that DOES need
 * per-keystroke timing calls `userEvent.setup()` itself.
 */
export const USER_EVENT_OPTIONS = {delay: null} as const;

/**
 * An initial router location: a path, or a path with the history state a navigation carried.
 *
 * The object form is for a page that reads `location.state` — a hand-off from another feature —
 * which a string cannot express. The state is held by the seam before `ui` mounts, as the state a
 * navigation carried to that page's first render.
 */
export type TestRoute = string | {pathname: string; search?: string; state?: unknown};

/** The address a route names, as one string. */
function hrefOfRoute(route: TestRoute): string {
  return typeof route === 'string' ? route : `${route.pathname}${route.search ?? ''}`;
}

/**
 * Put a test at `route` on jsdom's own history, which is the only history there is, and put the
 * address back once the test finishes, since that history outlives the test.
 *
 * @param route - Where the test starts.
 * @param resolver - How a path selects a page, for `renderApp`; none for a plain render.
 */
export function startAt(route: TestRoute, resolver: Parameters<typeof resetStandIn>[0] = null): void {
  const before = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  writeAddressRaw(null, hrefOfRoute(route));
  resetStandIn(resolver);
  onTestFinished(() => writeAddressRaw(null, before));
}

export type ProviderOptions = {
  /** Initial router location (default `/`). */
  route?: TestRoute;
  /** The pattern `ui` renders at, so its params resolve, e.g. '/data-quality/:space/:requestId'. */
  path?: string;
  /** Other patterns and what renders there, for a test whose subject navigates away. */
  routes?: Record<string, ReactElement>;
  /** Inject a fixed auth context. Pass `null` to omit the AuthContext provider
   *  (the component doesn't call `useAuth`). Defaults to an authenticated user. */
  auth?: AuthContextValue | null;
  /** Reuse a QueryClient (e.g. to seed or assert cache); a fresh one otherwise. */
  queryClient?: QueryClient;
  /**
   * Pre-resolve the feature flags to the compiled-in defaults (everything on).
   *
   * ON BY DEFAULT, because every gated surface waits on a fetch: without a
   * seeded answer, `useFeature` reports `false` while the query is pending and a test that
   * has nothing to do with flags asserts against a shell with no tabs, no "Create table" and
   * no Help sections. Seeding all-on is the same answer production reaches when the document
   * is unreadable, so a test's default world is the app at its most visible.
   *
   * Pass `false` when the flags themselves are the subject — `gatedSurfaces.test.tsx` mocks
   * the service and needs the real resolve to be what fills the cache.
   */
  seedFeatureFlags?: boolean;
  /**
   * Flags to seed over the compiled-in defaults, for a test that needs one switch off —
   * `{archive: false}` — while every other gated surface stays as the app at its most visible.
   *
   * Refused alongside `seedFeatureFlags: false`, where nothing would be seeded and the overrides
   * would be silently dropped.
   */
  featureFlags?: Partial<FeatureFlags>;
};

/**
 * Put the compiled-in flags in the cache under the key the hook will look for.
 *
 * Written through the SAME key factory the hook uses, so a change to the key shape cannot
 * leave every test silently un-seeded and every gated surface silently absent.
 */
function seedFlags(client: QueryClient, overrides: Partial<FeatureFlags> = {}): void {
  // `setQueryDefaults` FIRST, and it is not optional: the test client runs `gcTime: 0`, so a
  // seeded entry with no observer yet is evicted the moment it is written. Every gated
  // surface that mounts LATER — a control inside a drawer the test has to click open — would
  // then start from a cold, pending query and read as flagged off, while the same control
  // asserted at first paint passed. Infinite gc/stale keeps the seed alive and stops the real
  // service being called behind it.
  client.setQueryDefaults(featureFlagKeys.all, {gcTime: Infinity, staleTime: Infinity});
  client.setQueryData(featureFlagKeys.resolved(configValue('environment')), {...FEATURE_FLAG_DEFAULTS, ...overrides});
}

/** The client every render entry point seeds, or refuses overrides it could not seed. */
function seededClient(
  queryClient: QueryClient | undefined,
  seedFeatureFlags: boolean,
  featureFlags: Partial<FeatureFlags> | undefined
): QueryClient {
  if (featureFlags && !seedFeatureFlags)
    throw new Error('featureFlags needs seedFeatureFlags: the overrides would be dropped');
  const client = queryClient ?? createTestQueryClient();
  if (seedFeatureFlags) seedFlags(client, featureFlags);
  return client;
}

/** What the provider stack needs that the public options do not carry. */
type StackProps = {
  children: ReactNode;
  auth: AuthContextValue | null;
  client: QueryClient;
  initialState: unknown;
  /** react-router inside the seam, for `ui` that reads route params; `renderApp` brings its own. */
  catchAllRouter: boolean;
  onLocation?: (location: NavLocation) => void;
  /** The area records the seam, the chrome and the table read; the production records otherwise. */
  records?: readonly AreaRecord[];
};

/** Reports the seam's location after every commit, for the render result's `location()`. */
function LocationProbe({onLocation}: {onLocation: (location: NavLocation) => void}) {
  const location = useLocation();
  useLayoutEffect(() => onLocation(location), [location, onLocation]);
  return null;
}

/**
 * The harness's one provider stack: Next's stand-in, the query client, the auth context and the
 * seam, with the toasts inside. `TestProviders` adds react-router inside the seam; `renderApp` puts
 * the real chrome there instead. The shell's providers are never here: a test that wrapped the
 * shell's providers around the app would pass wherever the app put them.
 */
export function ProviderStack({
  children,
  auth,
  client,
  initialState,
  catchAllRouter,
  onLocation,
  records
}: StackProps): ReactElement {
  const content = <ToastProvider>{children}</ToastProvider>;
  const seam = (
    <NavigationProvider initialState={initialState}>
      {onLocation && <LocationProbe onLocation={onLocation} />}
      {catchAllRouter ? <CatchAllRouter>{content}</CatchAllRouter> : content}
    </NavigationProvider>
  );
  const tree = (
    <NextStandInRoot>
      <QueryClientProvider client={client}>
        {records ? <AreaRecordsContext.Provider value={records}>{seam}</AreaRecordsContext.Provider> : seam}
      </QueryClientProvider>
    </NextStandInRoot>
  );
  return auth ? <AuthContext.Provider value={auth}>{tree}</AuthContext.Provider> : tree;
}

/** `ui` alone, or at `path` beside the other `routes`, in react-router's table under the seam. */
function routed(ui: ReactNode, path: string | undefined, routes: Record<string, ReactElement> | undefined): ReactNode {
  if (path === undefined && routes === undefined) return ui;
  return (
    <Routes>
      <Route
        path={path ?? '*'}
        element={ui}
      />
      {Object.entries(routes ?? {}).map(([pattern, element]) => (
        <Route
          key={pattern}
          path={pattern}
          element={element}
        />
      ))}
    </Routes>
  );
}

/**
 * The provider stack as a component, for the few callers that cannot use
 * `renderWithProviders` — chiefly `expectNoA11yViolations`, which renders the element it is
 * given rather than accepting an already-rendered container. It puts the test at `route` itself.
 */
export function TestProviders({
  children,
  route = '/',
  path,
  routes,
  auth = authValue(),
  queryClient,
  seedFeatureFlags = true,
  featureFlags,
  onLocation,
  addressSeeded = false
}: ProviderOptions & {
  children: ReactNode;
  onLocation?: (location: NavLocation) => void;
  /** The render entry points put the test at its address before rendering; a direct caller does not. */
  addressSeeded?: boolean;
}): ReactElement {
  // Built here rather than required, so a direct caller (an axe render) gets the same seeded
  // client `renderWithProviders` would have handed it, at the address it asked for.
  const [client] = useState(() => {
    if (!addressSeeded) startAt(route);
    const created = seededClient(queryClient, seedFeatureFlags, featureFlags);
    // Only when this component owns the client: one passed in was already registered by the
    // `renderWithProviders`/`renderHookWithProviders` call that built it.
    if (!queryClient) clearAfterTest(created);
    return created;
  });
  return (
    <ProviderStack
      auth={auth}
      client={client}
      initialState={typeof route === 'object' ? route.state : undefined}
      catchAllRouter
      onLocation={onLocation}>
      {routed(children, path, routes)}
    </ProviderStack>
  );
}

export {seededClient, clearAfterTest};

/** Options only `renderWithProviders` takes: they shape the render, not the provider stack. */
export type RenderWithProvidersOptions = ProviderOptions & {
  /**
   * Render under `StrictMode`, as `AppFrame` does, so effects run twice on mount.
   *
   * React double-runs a subtree's effects only when the element it PLACES is `StrictMode` or sits
   * inside one — measured: a `StrictMode` handed in as `ui`, beneath the provider wrapper, runs
   * every effect once. So this renders `StrictMode` above the providers as the tree's root rather
   * than through `wrapper`, and a `rerender` must then be given that whole tree.
   */
  strictMode?: boolean;
};

export type RenderWithProvidersResult = ReturnType<typeof render> & {
  user: UserEvent;
  queryClient: QueryClient;
  /** The seam's location as it stands: where a navigation went, and what it carried. */
  location: () => NavLocation;
};

/** A holder for the seam's latest location, and the reader the render result hands out. */
export function locationRecorder(): {onLocation: (location: NavLocation) => void; location: () => NavLocation} {
  let latest: NavLocation | null = null;
  return {
    onLocation: (location) => {
      latest = location;
    },
    location: () => {
      if (!latest) throw new Error('the seam has not rendered yet');
      return latest;
    }
  };
}

/**
 * Renders `ui` inside the app's provider stack (the QueryClient, the AuthContext, and the
 * navigation seam on jsdom's own history through Next's stand-in, with react-router inside it so
 * route params resolve) and returns a `userEvent` instance and the seam's location alongside the
 * usual RTL result. This is the default entry point for component/feature tests — mock only the
 * AWS service boundary (`*.service.ts` / `src/lib` clients) and let the real hooks and child
 * components render.
 *
 * `path` puts `ui` at a pattern so its params resolve; `routes` adds other patterns, for a test
 * whose subject navigates away. The address is restored when the test finishes.
 */
export function renderWithProviders(
  ui: ReactElement,
  {
    route = '/',
    path,
    routes,
    auth,
    queryClient,
    seedFeatureFlags = true,
    featureFlags,
    strictMode = false,
    ...options
  }: RenderWithProvidersOptions & Omit<RenderOptions, 'wrapper'> = {}
): RenderWithProvidersResult {
  startAt(route);
  const client = seededClient(queryClient, seedFeatureFlags, featureFlags);
  clearAfterTest(client);
  const recorder = locationRecorder();
  const providers = (children: ReactNode) => (
    <TestProviders
      route={route}
      path={path}
      routes={routes}
      auth={auth}
      queryClient={client}
      seedFeatureFlags={seedFeatureFlags}
      featureFlags={featureFlags}
      onLocation={recorder.onLocation}
      addressSeeded>
      {children}
    </TestProviders>
  );
  const result = strictMode
    ? render(<StrictMode>{providers(ui)}</StrictMode>, options)
    : render(ui, {wrapper: ({children}) => providers(children), ...options});
  return {...result, user: userEvent.setup(USER_EVENT_OPTIONS), queryClient: client, location: recorder.location};
}

/**
 * `renderHook` wrapped in the same provider stack — for hooks that read
 * TanStack Query, the navigation seam, or auth. Returns the RTL result plus the
 * QueryClient so a test can assert cache state, and the seam's location.
 */
export function renderHookWithProviders<Result, Props>(
  hook: (props: Props) => Result,
  {
    route = '/',
    path,
    routes,
    auth,
    queryClient,
    seedFeatureFlags = true,
    featureFlags,
    ...options
  }: ProviderOptions & Omit<RenderHookOptions<Props>, 'wrapper'> = {}
) {
  startAt(route);
  const client = seededClient(queryClient, seedFeatureFlags, featureFlags);
  clearAfterTest(client);
  const recorder = locationRecorder();
  const result = renderHook(hook, {
    wrapper: ({children}) => (
      <TestProviders
        route={route}
        path={path}
        routes={routes}
        auth={auth}
        queryClient={client}
        seedFeatureFlags={seedFeatureFlags}
        featureFlags={featureFlags}
        onLocation={recorder.onLocation}
        addressSeeded>
        {children}
      </TestProviders>
    ),
    ...options
  });
  return {...result, queryClient: client, location: recorder.location};
}
