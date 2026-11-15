import {StrictMode, type ReactNode} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderApp as renderTheApp} from '../../test/appRouter';
import {wrappersOf} from '../../test/viewSource';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import QueryPage from '../QueryPage';
import {QueryRunsProvider} from '../../features/query/QueryRunsProvider';
import {
  editor,
  installWorkspaceMocks,
  mockGetResults,
  mockRunQuery,
  mockUpdate,
  queueRuns,
  resetViewport,
  seedSingle,
  seedTabs,
  statusMap
} from '../../test/queryWorkspaceSupport';
import {POLL_INTERVAL_MS} from '../../features/catalog/catalog.constants';
import {AuthContext} from '../../features/auth/authContext';
import {EXPLORATION_TABS_STORAGE_PREFIX} from '../../features/data-explorer/dataExplorer.constants';
import {newExploration} from '../../features/data-explorer/exploration';
import type {ExplorationTabsState} from '../../features/data-explorer/dataExplorer.types';
import {requests, traverse} from '../../test/nextNavigation';

/**
 * A Query run outlives the Query page, driven through the REAL chrome and route table.
 *
 * The page unmounts on every nav-tab click, so a run held there lost its results on the way back
 * and its poller on the way out. Only a render of the real shell can tell where the runs live: a
 * test that wraps the workspace in its own provider passes wherever the app puts it. Every
 * navigation is a click on a link the header renders, and each waits for its destination.
 */
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

const renderApp = () => renderTheApp('/query', {auth: authenticated('alice'), routers: {query: 'app'}});

type User = ReturnType<typeof renderApp>['user'];

/** Leave Query for the notifications page by its header link, and wait for it. */
async function leaveQuery(user: User) {
  await user.click(screen.getByRole('link', {name: /^Notifications,/}));
  await screen.findByRole('heading', {name: 'Notifications', level: 1});
}

/** Come back to Query by its nav tab, and wait for the editor. */
async function backToQuery(user: User) {
  await user.click(screen.getByRole('link', {name: 'Query'}));
  await screen.findByLabelText('SQL editor');
}

beforeEach(() => {
  installWorkspaceMocks();
  window.innerWidth = 1280;
});

afterEach(resetViewport);

describe('a Query run outlives the Query page', () => {
  it('shows the same results after leaving Query and coming back, without running again', async () => {
    queueRuns('q-1');
    seedSingle('SELECT region FROM alice.sales');
    const {user} = renderApp();
    await screen.findByLabelText('SQL editor');
    await user.click(screen.getByRole('button', {name: 'Run statement'}));
    await screen.findByText('us-east');

    await leaveQuery(user);
    await backToQuery(user);

    expect(await screen.findByText('us-east')).toBeInTheDocument();
    expect(screen.getByText('Succeeded')).toBeInTheDocument();
    // The cost of coming back: one execution in all, and its results read for the one execution.
    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    expect(mockGetResults.mock.calls.every(([args]) => args.queryExecutionId === 'q-1')).toBe(true);
  });

  it('keeps watching a running query while the user is on another page, and records its verdict', async () => {
    queueRuns('q-1');
    statusMap['q-1'] = {state: 'RUNNING'};
    seedSingle('SELECT region FROM alice.sales');
    const {user} = renderApp();
    await screen.findByLabelText('SQL editor');
    await user.click(screen.getByRole('button', {name: 'Run statement'}));
    await screen.findByRole('button', {name: 'Stop the running query'});

    await leaveQuery(user);
    delete statusMap['q-1'];

    // Settled while Query is not mounted: only a poller outside the page can read the verdict.
    await waitFor(
      () => expect(mockUpdate).toHaveBeenCalledWith('alice', 'q-1', expect.objectContaining({status: 'SUCCEEDED'})),
      {timeout: POLL_INTERVAL_MS * 3}
    );
    expect(screen.queryByLabelText('SQL editor')).not.toBeInTheDocument();

    await backToQuery(user);
    expect(await screen.findByText('us-east')).toBeInTheDocument();
  });

  // Session storage that failed brings the workspace back with new tab ids, and nothing could
  // reach the old tab's run again to show or stop it.
  it('drops a run whose tab did not come back, so nothing goes on watching it', async () => {
    queueRuns('q-1');
    statusMap['q-1'] = {state: 'RUNNING'};
    seedSingle('SELECT region FROM alice.sales');
    const {user} = renderApp();
    await screen.findByLabelText('SQL editor');
    await user.click(screen.getByRole('button', {name: 'Run statement'}));
    await screen.findByRole('button', {name: 'Stop the running query'});

    await leaveQuery(user);
    seedTabs({
      version: 1,
      tabs: [{id: 'fresh', label: 'Query 1', sql: 'SELECT 1'}],
      activeTabId: 'fresh',
      nextQueryNumber: 2
    });
    await backToQuery(user);
    delete statusMap['q-1'];
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS * 2));

    expect(mockUpdate).not.toHaveBeenCalled();
    expect(screen.getByRole('button', {name: 'Run statement'})).toBeInTheDocument();
  });
});

// ─── from routes.test.tsx ───

describe('QueryPage', () => {
  // The lazy Monaco editor is stubbed to a plain textarea so the route renders
  // without the editor chunk / web workers (react.md §21 "stub the heavy editor by
  // exception"). The workspace's data hooks resolve over the mocked services.

  beforeEach(() => {
    window.innerWidth = 1280;
  });

  describe('QueryPage route', () => {
    it('renders the query workspace for an authenticated user', async () => {
      renderWithProviders(
        <QueryRunsProvider username="alice">
          <QueryPage />
        </QueryRunsProvider>,
        {route: '/query', auth: authenticated('alice')}
      );

      // The workspace toolbar is present (real QueryWorkspace, real tab strip).
      expect(await screen.findByRole('button', {name: 'Run statement'})).toBeInTheDocument();
      // The lazy editor mounts (stubbed textarea) once its chunk resolves.
      expect(await screen.findByLabelText('SQL editor')).toBeInTheDocument();
    });

    it('sets the page title', () => {
      renderWithProviders(
        <QueryRunsProvider username="alice">
          <QueryPage />
        </QueryRunsProvider>,
        {route: '/query', auth: authenticated('alice')}
      );
      expect(document.title).toMatch(/Query/);
    });
  });
});

describe('the Query view', () => {
  const VIEW = Object.values(
    import.meta.glob('./query.tsx', {query: '?raw', import: 'default', eager: true})
  )[0] as string;

  it('wraps the page in FeatureRoute → ErrorBoundary → Suspense, in that order, behind the query flag', () => {
    expect(wrappersOf(VIEW, 'QueryPage')).toEqual(['FeatureRoute', 'ErrorBoundary', 'Suspense']);
    expect(VIEW).toContain('<FeatureRoute flag="query">');
  });
});

// ─── Query on the App Router ───

const SIGNED_IN = authenticated('alice');

/**
 * The signed-in auth context under `StrictMode`, as `AppFrame` renders it. React doubles the
 * effects of a subtree only when the fiber it places is or sits inside a `StrictMode`, so this
 * doubles every page a navigation mounts below it, which is the hazard a hand-off's receiver guards.
 */
function StrictlySignedIn({children}: {children: ReactNode}) {
  return (
    <StrictMode>
      <AuthContext.Provider value={SIGNED_IN}>{children}</AuthContext.Provider>
    </StrictMode>
  );
}

/** One exploration of `alice.sales_2026` with a filter, so its generated SQL says something. */
function seedExploration() {
  const exploration = newExploration(
    {kind: 'table', spaceId: 'personal', database: 'alice', table: 'sales_2026'},
    't1'
  );
  exploration.query = {
    ...exploration.query,
    filters: [{column: 'region', operator: '=', value: 'us-east', valueKind: 'string'}]
  };
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [{id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}}],
    activeTabId: 't1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

describe('the Query page', () => {
  it('serves /query from its App Router page, inside the shell', async () => {
    renderTheApp('/query', {auth: SIGNED_IN, routers: {query: 'app'}});
    // Settled on whichever renders, so a missing page fails on the catch-all's 404, not on a wait.
    await waitFor(() =>
      expect(
        screen.queryByLabelText('SQL editor') ?? screen.queryByRole('heading', {name: 'Page not found'})
      ).not.toBeNull()
    );

    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
    expect(screen.getByLabelText('SQL editor')).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main');
  });

  // The catch-all would serve /query without a request; only the App Router's page is fetched. The
  // page it leaves is pinned to the catch-all, because leaving an App Router page is a fetch whoever
  // serves the destination.
  it('is fetched from the server when the user arrives from a catch-all page', async () => {
    const {user} = renderTheApp('/notifications', {
      auth: SIGNED_IN,
      routers: {notifications: 'catch-all', query: 'app'}
    });
    await screen.findByRole('heading', {name: 'Notifications', level: 1});

    await user.click(screen.getByRole('link', {name: 'Query'}));

    expect(await screen.findByLabelText('SQL editor')).toBeInTheDocument();
    expect(requests()).toContain('/query');
  });
});

// The App Router row renders Explore's own page from disk; the catch-all row ignores it.
describe.each([
  ['the catch-all', 'catch-all'],
  ['the App Router', 'app']
] as const)('Open in Query from the Data Explorer served by %s', (_name, explore) => {
  it('opens one tab with the statement, and nothing more on Back and then Forward', async () => {
    seedExploration();
    const {user} = renderTheApp('/explore', {
      auth: StrictlySignedIn,
      routers: {explore, query: 'app'}
    });
    // The Explorer runs its query through the real workspace: a result is real rendering, slower
    // beside the rest of the suite, so its waits get a window of their own.
    await screen.findByRole('gridcell', {name: 'us-east'}, {timeout: 5_000});
    await user.click(screen.getByText('Generated SQL'));
    const sql = (screen.getByLabelText('Generated SQL') as HTMLTextAreaElement).value;

    await user.click(screen.getByRole('button', {name: 'Open in Query'}));

    expect(await screen.findByRole('tab', {name: /orders/})).toHaveAttribute('aria-selected', 'true');
    expect(editor().value).toBe(sql);
    expect(screen.getAllByRole('tab')).toHaveLength(2);

    await traverse(-1);
    await screen.findByRole('gridcell', {name: 'us-east'}, {timeout: 5_000});
    await traverse(1);
    await screen.findByLabelText('SQL editor');

    expect(screen.getAllByRole('tab')).toHaveLength(2);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });
});

// `requests()` is what catches a router replace: the stand-in keys a page by its file, not its search,
// so the page element survives one there; the element check catches a remount by any other cause.
describe('a refresh link on the Query page', () => {
  it('opens the dialog for its table, and dismissing it drops the parameters without fetching or remounting the page', async () => {
    const {user} = renderTheApp('/query?refreshTable=alice.sales_2026&removed=legacy_id', {
      auth: SIGNED_IN,
      routers: {query: 'app'}
    });
    const dialog = await screen.findByRole('alertdialog', {name: 'Confirm refresh table alice.sales_2026'});
    const page = screen.getByLabelText('SQL editor');
    const fetched = requests().length;

    await user.click(within(dialog).getByRole('button', {name: 'Cancel'}));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(window.location.pathname + window.location.search).toBe('/query');
    expect(requests()).toHaveLength(fetched);
    expect(screen.getByLabelText('SQL editor')).toBe(page);
  });
});
