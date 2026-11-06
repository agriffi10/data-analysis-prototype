import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {App} from './App';
import {renderWithProviders} from './test/renderWithProviders';
import {authenticated} from './test/authFixtures';
import {
  installWorkspaceMocks,
  mockGetResults,
  mockRunQuery,
  mockUpdate,
  queueRuns,
  resetViewport,
  seedSingle,
  statusMap
} from './test/queryWorkspaceSupport';
import {POLL_INTERVAL_MS} from './features/catalog/catalog.constants';

/**
 * A Query run outlives the Query page, driven through the REAL route table.
 *
 * The page unmounts on every nav-tab click, so a run held there lost its results on the way back
 * and its poller on the way out. Only a render of the real shell can tell where the runs live: a
 * test that wraps the workspace in its own provider passes wherever the app puts it. Every
 * navigation is a click on a link the header renders, and each waits for its destination.
 */
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));
vi.mock('./features/query/SqlEditor', () => import('./test/sqlEditorStub'));
vi.mock('./features/catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./features/catalog/athena.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getTableDdl: vi.fn(),
  runStatementToCompletion: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn(),
  getQueryRowCount: vi.fn()
}));
vi.mock('./features/catalog/glue.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./features/catalog/glue.service')>()),
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));
vi.mock('./features/query/queryHistory.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./features/query/queryHistory.service')>()),
  getQueryHistory: vi.fn(),
  appendQueryHistory: vi.fn(),
  updateQueryHistoryEntry: vi.fn()
}));
vi.mock('./features/saved-queries/savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./features/saved-queries/savedQueries.service')>()),
  ensureSavedQueriesFolder: vi.fn(),
  listSavedQueries: vi.fn(),
  readSavedQuery: vi.fn(),
  writeSavedQuery: vi.fn(),
  deleteSavedQuery: vi.fn()
}));
vi.mock('./features/shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./features/shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
vi.mock('./features/file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./features/file-browser/fileBrowser.service')>()),
  copyObject: vi.fn(),
  listFiles: vi.fn()
}));
vi.mock('./features/table-share/tableShare.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./features/table-share/tableShare.service')>()),
  enqueueTableShare: vi.fn()
}));
vi.mock('./features/table-builder/tableBuild.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./features/table-builder/tableBuild.service')>()),
  enqueueTableRefresh: vi.fn()
}));
vi.mock('./features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

const renderApp = () => renderWithProviders(<App />, {route: '/query', auth: authenticated('alice')});

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
});
