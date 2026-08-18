import {useState} from 'react';
import {render, renderHook} from '@testing-library/react';
import type {RenderOptions, RenderHookOptions} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type {UserEvent} from '@testing-library/user-event';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router';
import type {ReactElement, ReactNode} from 'react';
import {AuthContext} from '../features/auth/authContext';
import type {AuthContextValue} from '../features/auth/auth.types';
import {ToastProvider} from '../components/ToastProvider';
import {authValue} from './authFixtures';
import {FEATURE_FLAG_DEFAULTS, featureFlagKeys} from '../features/feature-flags';
import {envVar} from '../lib/env';

/**
 * QueryClient for tests: retries off (a mocked service rejection should fail the
 * assertion immediately, not after a backoff) and no caching between renders
 * (`staleTime`/`gcTime` 0) so each test starts from a cold cache. Prefer the
 * shared instance via `renderWithProviders`; construct one directly only when a
 * test needs to inspect the cache.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {retry: false, staleTime: 0, gcTime: 0},
      mutations: {retry: false}
    }
  });
}

/**
 * `delay: null` types the whole string in one go instead of yielding a macrotask per
 * keystroke — the default `delay: 0` costs a real event-loop turn per character, which
 * is pure overhead in a jsdom suite with no debounce to exercise. A test that DOES need
 * per-keystroke timing calls `userEvent.setup()` itself.
 */
export const USER_EVENT_OPTIONS = {delay: null} as const;

export type ProviderOptions = {
  /** Initial router location (default `/`). */
  route?: string;
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
};

/**
 * Put the compiled-in flags in the cache under the key the hook will look for.
 *
 * Written through the SAME key factory the hook uses, so a change to the key shape cannot
 * leave every test silently un-seeded and every gated surface silently absent.
 */
function seedFlags(client: QueryClient): void {
  // `setQueryDefaults` FIRST, and it is not optional: the test client runs `gcTime: 0`, so a
  // seeded entry with no observer yet is evicted the moment it is written. Every gated
  // surface that mounts LATER — a control inside a drawer the test has to click open — would
  // then start from a cold, pending query and read as flagged off, while the same control
  // asserted at first paint passed. Infinite gc/stale keeps the seed alive and stops the real
  // service being called behind it.
  client.setQueryDefaults(featureFlagKeys.all, {gcTime: Infinity, staleTime: Infinity});
  client.setQueryData(featureFlagKeys.resolved(envVar('VITE_ENVIRONMENT')), FEATURE_FLAG_DEFAULTS);
}

/**
 * The provider stack as a component, for the few callers that cannot use
 * `renderWithProviders` — chiefly `expectNoA11yViolations`, which renders the element it is
 * given rather than accepting an already-rendered container.
 */
export function TestProviders({
  children,
  route = '/',
  auth = authValue(),
  queryClient,
  seedFeatureFlags = true
}: ProviderOptions & {children: ReactNode}): ReactElement {
  // Built here rather than required, so a direct caller (an axe render) gets the same seeded
  // client `renderWithProviders` would have handed it.
  const [client] = useState(() => {
    const created = queryClient ?? createTestQueryClient();
    if (seedFeatureFlags) seedFlags(created);
    return created;
  });
  const tree = (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <ToastProvider>{children}</ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return auth ? <AuthContext.Provider value={auth}>{tree}</AuthContext.Provider> : tree;
}

export type RenderWithProvidersResult = ReturnType<typeof render> & {
  user: UserEvent;
  queryClient: QueryClient;
};

/**
 * Renders `ui` inside the app's provider stack (QueryClient + MemoryRouter +
 * AuthContext) and returns a `userEvent` instance alongside the usual RTL
 * result. This is the default entry point for component/feature tests — mock
 * only the AWS service boundary (`*.service.ts` / `src/lib` clients) and let the
 * real hooks and child components render.
 */
export function renderWithProviders(
  ui: ReactElement,
  {route, auth, queryClient, seedFeatureFlags = true, ...options}: ProviderOptions & Omit<RenderOptions, 'wrapper'> = {}
): RenderWithProvidersResult {
  const client = queryClient ?? createTestQueryClient();
  if (seedFeatureFlags) seedFlags(client);
  const result = render(ui, {
    wrapper: ({children}) => (
      <TestProviders
        route={route}
        auth={auth}
        queryClient={client}
        seedFeatureFlags={seedFeatureFlags}>
        {children}
      </TestProviders>
    ),
    ...options
  });
  return {...result, user: userEvent.setup(USER_EVENT_OPTIONS), queryClient: client};
}

/**
 * `renderHook` wrapped in the same provider stack — for hooks that read
 * TanStack Query, the router, or auth. Returns the RTL result plus the
 * QueryClient so a test can assert cache state.
 */
export function renderHookWithProviders<Result, Props>(
  hook: (props: Props) => Result,
  {
    route,
    auth,
    queryClient,
    seedFeatureFlags = true,
    ...options
  }: ProviderOptions & Omit<RenderHookOptions<Props>, 'wrapper'> = {}
) {
  const client = queryClient ?? createTestQueryClient();
  if (seedFeatureFlags) seedFlags(client);
  const result = renderHook(hook, {
    wrapper: ({children}) => (
      <TestProviders
        route={route}
        auth={auth}
        queryClient={client}
        seedFeatureFlags={seedFeatureFlags}>
        {children}
      </TestProviders>
    ),
    ...options
  });
  return {...result, queryClient: client};
}
