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
};

function Providers({
  children,
  route = '/',
  auth = authValue(),
  queryClient
}: ProviderOptions & {children: ReactNode; queryClient: QueryClient}): ReactElement {
  const tree = (
    <QueryClientProvider client={queryClient}>
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
  {route, auth, queryClient, ...options}: ProviderOptions & Omit<RenderOptions, 'wrapper'> = {}
): RenderWithProvidersResult {
  const client = queryClient ?? createTestQueryClient();
  const result = render(ui, {
    wrapper: ({children}) => (
      <Providers
        route={route}
        auth={auth}
        queryClient={client}>
        {children}
      </Providers>
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
  {route, auth, queryClient, ...options}: ProviderOptions & Omit<RenderHookOptions<Props>, 'wrapper'> = {}
) {
  const client = queryClient ?? createTestQueryClient();
  const result = renderHook(hook, {
    wrapper: ({children}) => (
      <Providers
        route={route}
        auth={auth}
        queryClient={client}>
        {children}
      </Providers>
    ),
    ...options
  });
  return {...result, queryClient: client};
}
