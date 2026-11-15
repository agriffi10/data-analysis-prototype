import {StrictMode, type ReactNode} from 'react';
import {afterEach, beforeEach, describe, it, expect, vi} from 'vitest';
import {act, screen, waitFor} from '@testing-library/react';
import {QueryClient} from '@tanstack/react-query';
import {renderApp} from '../../test/appRouter';
import {authenticated} from '../../test/authFixtures';
import {wrappersOf} from '../../test/viewSource';
import {nextPopstate, requests, traverse} from '../../test/nextNavigation';
import {
  installWorkspaceMocks,
  mockReadCache,
  mockRunQuery,
  ok,
  openTableMenu,
  resetViewport,
  seedSingle
} from '../../test/queryWorkspaceSupport';
import {AuthContext} from '../../features/auth/authContext';
import {connectionKeys} from '../../features/connections';
import type {SharedConnectionsCache} from '../../features/shared-spaces/sharedSpaces.types';
import {Link} from '../../lib/navigation';
import {QueryView} from './query';

// Below this line, what the App Router's Explorer page is proved with. Every service either page
// reaches is mocked at its boundary, so nothing here leans on the Amplify mock above.
vi.mock('../../features/query/SqlEditor', () => import('../../test/sqlEditorStub'));
vi.mock('../../features/catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/catalog/athena.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getTableDdl: vi.fn(),
  runStatementToCompletion: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn(),
  getQueryRowCount: vi.fn()
}));
vi.mock('../../features/catalog/glue.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/catalog/glue.service')>()),
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));
vi.mock('../../features/query/queryHistory.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/query/queryHistory.service')>()),
  getQueryHistory: vi.fn(),
  appendQueryHistory: vi.fn(),
  updateQueryHistoryEntry: vi.fn()
}));
vi.mock('../../features/saved-queries/savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/saved-queries/savedQueries.service')>()),
  ensureSavedQueriesFolder: vi.fn(),
  listSavedQueries: vi.fn(),
  readSavedQuery: vi.fn(),
  writeSavedQuery: vi.fn(),
  deleteSavedQuery: vi.fn()
}));
vi.mock('../../features/shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
vi.mock('../../features/file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/file-browser/fileBrowser.service')>()),
  copyObject: vi.fn(),
  listFiles: vi.fn()
}));
vi.mock('../../features/table-share/tableShare.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/table-share/tableShare.service')>()),
  enqueueTableShare: vi.fn()
}));
vi.mock('../../features/table-builder/tableBuild.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/table-builder/tableBuild.service')>()),
  enqueueTableRefresh: vi.fn()
}));
vi.mock('../../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

/** How many times the Explorer's page has rendered: a pass-through, so the real page still renders. */
const explorerPage = vi.hoisted(() => ({renders: 0}));
vi.mock('../ExplorePage', async (importOriginal) => {
  const {createElement} = await import('react');
  const actual = await importOriginal<typeof import('../ExplorePage')>();
  return {
    default: function CountedExplorePage() {
      explorerPage.renders += 1;
      return createElement(actual.default);
    }
  };
});

const VIEW = Object.values(
  import.meta.glob('./explore.tsx', {query: '?raw', import: 'default', eager: true})
)[0] as string;

describe('App routing', () => {
  // The path is `/explore`, it is not the 404, and the lazy chunk resolves — the picker is the
  // page's own first surface, so finding it proves the route matched and the view mounted behind
  // Suspense.
  it('renders the Data Explorer at /explore', async () => {
    renderApp('/explore', {auth: authenticated('alice'), routers: {explore: 'app'}});

    expect(await screen.findByRole('region', {name: 'Choose a table to explore'})).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
    // The skip link's target: without it, "Skip to main content" does nothing on this page.
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main');
  });

  // A lazy view with no ErrorBoundary unmounts the tree on a chunk-load rejection, and `Suspense`
  // has no error path of its own (the accepted rollover race). What can only be checked here is
  // that this view is WRAPPED in one — and inside the gate, so the page cannot start fetching
  // before the flag answer arrives.
  it('wraps /explore in FeatureRoute → ErrorBoundary → Suspense, in that order', () => {
    expect(wrappersOf(VIEW, 'ExplorePage')).toEqual(['FeatureRoute', 'ErrorBoundary', 'Suspense']);
    // And the gate is the RIGHT flag. Without this line, changing it to `flag="query"` left the
    // whole suite green — a flag bypass no test could see.
    expect(VIEW).toContain('<FeatureRoute flag="dataExplorer">');
  });
});

// ─── served by the App Router ───

const ALICE = authenticated('alice');
const TEAM_LINK = '/explore?space=teamspace&db=teamspace&table=sales';
const NO_SPACES: SharedConnectionsCache = {version: 1, connections: []};
const TEAMSPACE: SharedConnectionsCache = {
  version: 1,
  connections: [{name: 'teamspace', role: 'member', status: 'active'}]
};

/** A client that keeps everything, so a page that remounts reads what is cached rather than running again. */
function keepAllClient(): QueryClient {
  return new QueryClient({defaultOptions: {queries: {retry: false, gcTime: Infinity, staleTime: Infinity}}});
}

/** The statements the Explorer ran over a handed-over Query statement, which it wraps as a subquery. */
function wrappedRuns(): string[] {
  return mockRunQuery.mock.calls.map(([call]) => (call as {sql: string}).sql).filter((sql) => sql.includes(') AS t'));
}

/**
 * Alice signed in, under `StrictMode` as `AppFrame` renders it. The Explorer mounts in a commit after
 * the first, beneath a `StrictMode` already mounted, so its effects run twice as they do in the app.
 */
function StrictAlice({children}: {children: ReactNode}) {
  return (
    <StrictMode>
      <AuthContext.Provider value={ALICE}>{children}</AuthContext.Provider>
    </StrictMode>
  );
}

/** Query as an App Router page, for as long as Query has none on disk; it replaces one that lands. */
function QueryAppRouterPage() {
  return <QueryView />;
}

/**
 * A signed-in page linking to a table in a space the cached list lacks, standing in for wherever such
 * a link is followed from. Followed, the link carries a key of its own, which a page loaded at the
 * address does not: there the entry's key is already `'default'`, as an in-page anchor's is.
 */
function TeamLinkPage() {
  return <Link to={TEAM_LINK}>Open the team’s table</Link>;
}

/** The linking page served in the notifications slot, whatever is on disk there, and the Explorer by its own page. */
const FROM_A_LINKING_PAGE = {
  routers: {notifications: 'app', explore: 'app'},
  pages: {'(signed-in)/notifications/page.tsx': TeamLinkPage}
} as const;

/** Wait until the address shows a page, its own or the catch-all's 404 in its place, and require its own. */
async function expectOwnPage(own: () => HTMLElement | null) {
  await waitFor(() => expect(own() ?? screen.queryByRole('heading', {name: 'Page not found'})).not.toBeNull());
  expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
  expect(own()).toBeInTheDocument();
}

/** Follow the shell's skip link, an in-page anchor, and wait for the traversal it makes. */
async function followSkipLink(user: ReturnType<typeof renderApp>['user']) {
  await act(async () => {
    const moved = nextPopstate();
    await user.click(screen.getByRole('link', {name: 'Skip to main content'}));
    await moved;
  });
}

beforeEach(() => {
  installWorkspaceMocks();
  let executions = 0;
  mockRunQuery.mockImplementation(async () => ok({queryExecutionId: `q-${(executions += 1)}`}));
  explorerPage.renders = 0;
  window.innerWidth = 1280;
});

afterEach(resetViewport);

describe('the Data Explorer on the App Router', () => {
  it('is served by its own page: its tab goes through Next’s router, and the page shows its picker', async () => {
    // Help pinned to the catch-all, so the request below is Explore's router speaking, not Help's.
    const {user} = renderApp('/help', {auth: ALICE, routers: {help: 'catch-all', explore: 'app'}});

    await user.click(await screen.findByRole('link', {name: 'Data Explorer'}));

    await expectOwnPage(() => screen.queryByRole('region', {name: 'Choose a table to explore'}));
    expect(requests()).toEqual(['/explore']);
    // The counter reaches the page the view loads, so the flag-off test's zero means something.
    expect(explorerPage.renders).toBeGreaterThan(0);
  });

  it('shows the unavailable page with the Data Explorer flag off, and never renders the Explorer’s page', async () => {
    renderApp('/explore', {auth: ALICE, routers: {explore: 'app'}, featureFlags: {dataExplorer: false}});

    expect(await screen.findByRole('heading', {name: 'Data Explorer isn’t available'})).toBeInTheDocument();
    // The page's module has resolved, so a render the gate let through has happened by now.
    await act(() => import('../ExplorePage'));
    expect(explorerPage.renders).toBe(0);
  });
});

describe('the Explorer’s deep links, hand-offs and link waits on the App Router', () => {
  it('opens a linked table, drops the link from the address without Next’s router, and a reload opens it once', async () => {
    const {location, unmount} = renderApp('/explore?space=personal&db=alice&table=sales', {
      auth: ALICE,
      routers: {explore: 'app'}
    });

    expect(await screen.findByRole('tab', {name: 'sales'})).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(window.location.search).toBe(''));
    expect(window.location.pathname).toBe('/explore');
    expect(location()).toMatchObject({pathname: '/explore', search: ''});
    // Dropped natively: no request for the page, so it was neither fetched again nor remounted.
    expect(requests()).toEqual([]);

    // A reload: a fresh page at the address the drop left, on the same session's storage.
    unmount();
    renderApp(`${window.location.pathname}${window.location.search}`, {auth: ALICE, routers: {explore: 'app'}});
    expect(await screen.findByRole('tab', {name: 'sales'})).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(1);
  });

  it.each([
    ['the catch-all', {routers: {query: 'catch-all', explore: 'app'}}],
    [
      'the App Router',
      {routers: {query: 'app', explore: 'app'}, pages: {'(signed-in)/query/page.tsx': QueryAppRouterPage}}
    ]
  ] as const)(
    'opens one tab for a statement handed over from Query on %s, and nothing on Back then Forward',
    async (_, serving) => {
      seedSingle('SELECT region FROM alice.sales');
      const {user} = renderApp('/query', {auth: StrictAlice, queryClient: keepAllClient(), ...serving});
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('us-east');

      await user.click(screen.getByRole('button', {name: 'Explore in Data Explorer'}));

      // Each of these navigations loads its destination's chunks, which is slow under load.
      const crossing = {timeout: 5000};
      const handedOver = {name: /^SELECT region FROM alice\.sales/};
      expect(await screen.findByRole('tab', handedOver, crossing)).toHaveAttribute('aria-selected', 'true');
      expect(screen.getAllByRole('tab')).toHaveLength(1);
      await waitFor(() => expect(wrappedRuns()).toHaveLength(1));

      await traverse(-1);
      await screen.findByLabelText('SQL editor', {}, crossing);
      await traverse(1);

      expect(await screen.findByRole('tab', handedOver, crossing)).toBeInTheDocument();
      expect(screen.getAllByRole('tab')).toHaveLength(1);
      expect(screen.queryByRole('alertdialog', {name: 'Exploration limit reached'})).not.toBeInTheDocument();
      // A hand-off delivered again re-runs its statement, which the kept cache would otherwise answer.
      expect(wrappedRuns()).toHaveLength(1);
    },
    20_000
  );

  it.each([
    ['the catch-all', {routers: {query: 'catch-all', explore: 'app'}}],
    [
      'the App Router',
      {routers: {query: 'app', explore: 'app'}, pages: {'(signed-in)/query/page.tsx': QueryAppRouterPage}}
    ]
  ] as const)(
    'opens a table from Query’s schema rail on %s, by a link the Explorer drops once it has read it',
    async (_, serving) => {
      const {user, location} = renderApp('/query', {auth: ALICE, ...serving});

      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'Explore data'}));

      const crossing = {timeout: 5000};
      expect(await screen.findByRole('tab', {name: 'sales_2026'}, crossing)).toHaveAttribute('aria-selected', 'true');
      expect(requests()).toEqual(['/explore?space=alice&db=alice&table=sales_2026']);
      await waitFor(() => expect(location()).toMatchObject({pathname: '/explore', search: ''}));
      expect(screen.getAllByRole('tab')).toHaveLength(1);
    },
    20_000
  );

  it('waits for a read after the link before it opens a space the cached list lacks, and the skip link asks for no other', async () => {
    const client = keepAllClient();
    client.setQueryData(connectionKeys.list('alice'), NO_SPACES);
    let settleRead: (result: ReturnType<typeof ok<SharedConnectionsCache>>) => void = () => {};
    mockReadCache.mockReturnValue(new Promise((resolve) => (settleRead = resolve)));
    const {user, location} = renderApp('/notifications', {auth: ALICE, queryClient: client, ...FROM_A_LINKING_PAGE});
    await user.click(await screen.findByRole('link', {name: 'Open the team’s table'}));
    // A followed link carries a key of its own: the skip link's `'default'` must be a change.
    await waitFor(() =>
      expect(location()).toMatchObject({pathname: '/explore', search: expect.stringContaining('space=teamspace')})
    );
    expect(location().key).not.toBe('default');

    await waitFor(() => expect(mockReadCache).toHaveBeenCalledOnce());
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: 'You don’t have access to that space'})).not.toBeInTheDocument();

    await followSkipLink(user);
    expect(location()).toMatchObject({hash: '#main', key: 'default'});
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(mockReadCache).toHaveBeenCalledOnce();

    await act(async () => settleRead(ok(TEAMSPACE)));
    expect(await screen.findByRole('tab', {name: 'sales'})).toBeInTheDocument();
    expect(mockReadCache).toHaveBeenCalledOnce();
  });

  it('refuses a space the read after the link also lacks, and the skip link on the refusal asks for no other read', async () => {
    const client = keepAllClient();
    client.setQueryData(connectionKeys.list('alice'), NO_SPACES);
    mockReadCache.mockResolvedValue(ok(NO_SPACES));
    const {user, location} = renderApp('/notifications', {auth: ALICE, queryClient: client, ...FROM_A_LINKING_PAGE});
    await user.click(await screen.findByRole('link', {name: 'Open the team’s table'}));
    // A followed link carries a key of its own: the skip link's `'default'` must be a change.
    await waitFor(() =>
      expect(location()).toMatchObject({pathname: '/explore', search: expect.stringContaining('space=teamspace')})
    );
    expect(location().key).not.toBe('default');

    expect(await screen.findByRole('heading', {name: 'You don’t have access to that space'})).toBeInTheDocument();
    expect(mockReadCache).toHaveBeenCalledOnce();

    // A traversal is not a follow: counted as one, this click would ask for the read again.
    await followSkipLink(user);
    expect(location()).toMatchObject({hash: '#main', key: 'default'});
    expect(mockReadCache).toHaveBeenCalledOnce();
    expect(screen.getByRole('heading', {name: 'You don’t have access to that space'})).toBeInTheDocument();
  });
});
