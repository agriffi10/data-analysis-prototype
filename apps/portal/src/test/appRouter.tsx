import type {ComponentType, ReactNode} from 'react';
import {render} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {AppChrome} from '../AppChrome';
import {AREAS, areaOf, type AreaName, type AreaRecord, type AreaRouter} from '../lib/navigation';
import type {AuthContextValue} from '../features/auth/auth.types';
import {authValue} from './authFixtures';
import {useStandInTree} from './nextNavigation';
import {patternOf, selectPage} from './pageSelection';
import {
  CATCH_ALL_RECORDS,
  ProviderStack,
  USER_EVENT_OPTIONS,
  clearAfterTest,
  locationRecorder,
  seededClient,
  startAt,
  type ProviderOptions,
  type RenderWithProvidersResult,
  type TestRoute
} from './renderWithProviders';

/** Every page file on disk, keyed by its path under `src/app/`. */
const DISK_PAGES: Record<string, ComponentType> = Object.fromEntries(
  Object.entries(import.meta.glob<{default: ComponentType}>('../app/**/page.tsx', {eager: true})).map(
    ([file, module]) => [file.slice('../app/'.length), module.default]
  )
);

/** The area a signed-in page file serves, or null for a page outside `(signed-in)/`. */
function areaOfPage(file: string): AreaName | null {
  if (!file.startsWith('(signed-in)/')) return null;
  const pattern = patternOf(file);
  return pattern ? (areaOf(pattern)?.area ?? null) : null;
}

export type RenderAppOptions = Omit<ProviderOptions, 'route' | 'path' | 'routes' | 'auth'> & {
  /** A fixed auth value, or a component providing the auth context for a test whose subject is the status changing. */
  auth?: AuthContextValue | ComponentType<{children: ReactNode}>;
  /** Page files keyed by their path under src/app/, added beside those on disk or replacing one at the same path. */
  pages?: Record<string, ComponentType>;
  /**
   * Which router serves an area in this test, whatever is on disk: every area the catch-all unless
   * named here, and an area on the catch-all has its pages ignored. `'as-recorded'` follows the
   * production records instead, for a test about the tree as it stands.
   */
  routers?: Partial<Record<AreaName, AreaRouter>> | 'as-recorded';
};

/**
 * The page files this render serves: those on disk and those `pages` adds, less the pages of every
 * area the catch-all serves in this render.
 */
export function pagesFor(
  disk: Record<string, ComponentType>,
  pages: Record<string, ComponentType>,
  records: readonly AreaRecord[]
): Record<string, ComponentType> {
  const all = {...disk, ...pages};
  return Object.fromEntries(
    Object.entries(all).filter(([file]) => {
      const area = areaOfPage(file);
      return area === null || records.find((record) => record.area === area)?.router === 'app';
    })
  );
}

/** The page the router last navigated to, as Next's own segment rendering selects it. */
function SelectedPage({files}: {files: Record<string, ComponentType>}) {
  const tree = useStandInTree();
  const selected = selectPage(Object.keys(files), new URL(tree, window.location.origin).pathname);
  if (!selected) return null;
  const Page = files[selected.file];
  // A different page, or the same dynamic page with other params, is a different segment, and Next
  // remounts it; a native navigation leaves the tree, and so the page, as it was.
  return <Page key={`${selected.file}:${JSON.stringify(selected.params)}`} />;
}

/**
 * The test App Router: the real `AppChrome` (`RootLayout`, the gate and the shell) under the
 * harness's providers, around the page Next's stand-in selects from the file system, as the real
 * one does. What sits above `AppChrome` in production is composition, held by the page sweep.
 *
 * The page is chosen by the stand-in's router state, never by the address, because a native
 * navigation moves the address and leaves the page as it was. Every area is served by the catch-all
 * unless `routers` names it, never by the production records, so an area move changes no test that
 * does not ask for it and a test that crosses the two routers holds in whatever order the moves land.
 *
 * @param route - Where the test starts.
 * @param options - The auth, the extra pages and the routers, beside the provider options.
 * @returns The render result, a `userEvent`, the query client and the seam's location.
 *
 * @example
 * const {user} = renderApp('/files', {auth: authenticated('alice'), routers: {files: 'app'}, pages});
 */
export function renderApp(
  route: TestRoute,
  {
    auth = authValue(),
    pages = {},
    routers = {},
    queryClient,
    seedFeatureFlags = true,
    featureFlags
  }: RenderAppOptions = {}
): RenderWithProvidersResult {
  const records =
    routers === 'as-recorded'
      ? AREAS
      : CATCH_ALL_RECORDS.map((record) => ({...record, router: routers[record.area] ?? record.router}));
  const files = pagesFor(DISK_PAGES, pages, records);
  startAt(route, (pathname) => selectPage(Object.keys(files), pathname));
  const client = seededClient(queryClient, seedFeatureFlags, featureFlags);
  clearAfterTest(client);
  const recorder = locationRecorder();
  const AuthComponent = typeof auth === 'function' ? auth : null;
  const stack = (
    <ProviderStack
      auth={AuthComponent ? null : (auth as AuthContextValue)}
      client={client}
      initialState={typeof route === 'object' ? route.state : undefined}
      catchAllRouter={false}
      onLocation={recorder.onLocation}
      records={records}>
      <AppChrome>
        <SelectedPage files={files} />
      </AppChrome>
    </ProviderStack>
  );
  const result = render(AuthComponent ? <AuthComponent>{stack}</AuthComponent> : stack);
  return {...result, user: userEvent.setup(USER_EVENT_OPTIONS), queryClient: client, location: recorder.location};
}
