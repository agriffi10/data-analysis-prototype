import type {ComponentType, ReactNode} from 'react';
import {render} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {AppChrome} from '../AppChrome';
import type {AuthContextValue} from '../features/auth/auth.types';
import {authValue} from './authFixtures';
import {useStandInTree} from './nextNavigation';
import {selectPage} from './pageSelection';
import {
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

/**
 * The root not-found page, read from disk rather than imported, so that with it deleted the tests
 * of the not-found page fail and every other render still runs.
 */
const NOT_FOUND: ComponentType | null =
  Object.values(import.meta.glob<{default: ComponentType}>('../app/not-found.tsx', {eager: true}))[0]?.default ?? null;

export type RenderAppOptions = Omit<ProviderOptions, 'route' | 'path' | 'routes' | 'auth'> & {
  /** A fixed auth value, or a component providing the auth context for a test whose subject is the status changing. */
  auth?: AuthContextValue | ComponentType<{children: ReactNode}>;
  /** Page files keyed by their path under src/app/, added beside those on disk or replacing one at the same path. */
  pages?: Record<string, ComponentType>;
};

/** The page the router last navigated to, as Next's own segment rendering selects it. */
function SelectedPage({files}: {files: Record<string, ComponentType>}) {
  const tree = useStandInTree();
  const selected = selectPage(Object.keys(files), new URL(tree, window.location.origin).pathname);
  if (!selected) return NOT_FOUND ? <NOT_FOUND /> : null;
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
 * navigation moves the address and leaves the page as it was. An address no page serves renders the
 * root `not-found.tsx` when the test starts there, as Next's document does; a navigation to one is a
 * document load, recorded in the stand-in's `documentLoads()`, as Next's is.
 *
 * @param route - Where the test starts.
 * @param options - The auth and the extra pages, beside the provider options.
 * @returns The render result, a `userEvent`, the query client and the seam's location.
 *
 * @example
 * const {user} = renderApp('/files', {auth: authenticated('alice'), pages});
 */
export function renderApp(
  route: TestRoute,
  {auth = authValue(), pages = {}, queryClient, seedFeatureFlags = true, featureFlags}: RenderAppOptions = {}
): RenderWithProvidersResult {
  const files = {...DISK_PAGES, ...pages};
  startAt(route, (pathname) => selectPage(Object.keys(files), pathname), true);
  const client = seededClient(queryClient, seedFeatureFlags, featureFlags);
  clearAfterTest(client);
  const recorder = locationRecorder();
  const AuthComponent = typeof auth === 'function' ? auth : null;
  const stack = (
    <ProviderStack
      auth={AuthComponent ? null : (auth as AuthContextValue)}
      client={client}
      initialState={typeof route === 'object' ? route.state : undefined}
      onLocation={recorder.onLocation}>
      <AppChrome>
        <SelectedPage files={files} />
      </AppChrome>
    </ProviderStack>
  );
  const result = render(AuthComponent ? <AuthComponent>{stack}</AuthComponent> : stack);
  return {...result, user: userEvent.setup(USER_EVENT_OPTIONS), queryClient: client, location: recorder.location};
}
