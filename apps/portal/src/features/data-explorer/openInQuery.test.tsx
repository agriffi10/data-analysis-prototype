import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {Route, Routes, useNavigate} from 'react-router';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {NOTHING_TO_OPEN} from './ExplorationResultsRegion';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState} from './dataExplorer.types';

// The Explorer half of *Open in Query*: the statement the disclosure shows leaves in router state,
// never in the URL, and the exploration it came from is untouched when the user comes back.

vi.mock('../catalog/glue.service', () => ({getDatabase: vi.fn(), listTables: vi.fn()}));
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn()
}));

const ok = <T,>(data: T) => ({success: true as const, data});
const STORAGE_KEY = `${EXPLORATION_TABS_STORAGE_PREFIX}alice`;

/** Stands in for the Query page: somewhere to land, and a way back. */
function QueryPage() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate('/explore')}>
      Back to the Data Explorer
    </button>
  );
}

function seedTab(expression: string | null = null) {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  exploration.query = {
    ...exploration.query,
    filters: [{column: 'state', operator: '=', value: 'NY', valueKind: 'string'}],
    expression
  };
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [
      {
        id: 't1',
        label: 'orders',
        exploration,
        scannedByExecution: {},
        history: {past: [], future: []}
      }
    ],
    activeTabId: 't1'
  };
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

/** What the round trip must leave alone, read from where the workspace keeps it. */
function persistedTab() {
  const [tab] = (JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '{}') as ExplorationTabsState).tabs;
  return {query: tab.exploration.query, presentation: tab.exploration.presentation, history: tab.history};
}

function renderRoutes() {
  return renderWithProviders(
    <Routes>
      <Route
        path="/explore"
        element={<DataExplorerWorkspace />}
      />
      <Route
        path="/query"
        element={<QueryPage />}
      />
    </Routes>,
    {route: '/explore', auth: authenticated('alice'), browserRouter: true}
  );
}

/** Renders both routes on jsdom's own history, settles the first run, and opens the disclosure. */
async function renderWithSqlShown() {
  const view = renderRoutes();
  await screen.findByRole('gridcell', {name: 'NY'});
  await view.user.click(screen.getByText('Generated SQL'));
  const sql = (screen.getByLabelText('Generated SQL') as HTMLTextAreaElement).value;
  return {...view, sql};
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);
  vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: 'exec-1'}) as never);
  vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
    ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})) as never);
  vi.mocked(getQueryResults).mockResolvedValue(
    ok({columns: [{name: 'state', type: 'varchar'}], rows: [['NY']]}) as never
  );
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('Open in Query', () => {
  it('takes the shown statement and the tab’s label to Query in router state, not the URL', async () => {
    const {user, sql} = await renderWithSqlShown();

    await user.click(screen.getByRole('button', {name: 'Open in Query'}));

    expect(await screen.findByRole('button', {name: 'Back to the Data Explorer'})).toBeInTheDocument();
    expect(window.location.pathname).toBe('/query');
    expect(window.location.search).toBe('');
    expect(sql).toContain(`"state" = 'NY'`);
    expect((window.history.state as {usr: unknown}).usr).toEqual({openSql: {sql, label: 'orders'}});
  });

  it('leaves the exploration as it was for when the user comes back', async () => {
    const {user} = await renderWithSqlShown();
    const before = persistedTab();
    await user.click(screen.getByRole('button', {name: 'Open in Query'}));

    await user.click(await screen.findByRole('button', {name: 'Back to the Data Explorer'}));

    expect(await screen.findByRole('tab', {name: /orders/})).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByRole('gridcell', {name: 'NY'})).toBeInTheDocument();
    expect(persistedTab()).toEqual(before);
  });

  it('goes from the Options menu too, with the same statement', async () => {
    const {user, sql} = await renderWithSqlShown();

    await user.click(screen.getByRole('button', {name: 'Options'}));
    await user.click(screen.getByRole('menuitem', {name: 'Open in Query'}));

    expect(await screen.findByRole('button', {name: 'Back to the Data Explorer'})).toBeInTheDocument();
    expect((window.history.state as {usr: unknown}).usr).toEqual({openSql: {sql, label: 'orders'}});
  });

  it('refuses from the Options menu, saying why, when there is no statement to open', async () => {
    // Too long for Athena, so it never renders into a statement at all.
    sessionStorage.clear();
    seedTab(`state = '${'x'.repeat(270_000)}'`);
    const {user} = renderRoutes();
    await screen.findByRole('button', {name: 'Options'});

    await user.click(screen.getByRole('button', {name: 'Options'}));
    const item = screen.getByRole('menuitem', {name: 'Open in Query'});
    await user.click(item);

    expect(item).toHaveAttribute('title', NOTHING_TO_OPEN);
    expect(window.location.pathname).toBe('/explore');
    expect(runQuery).not.toHaveBeenCalled();
  });
});
