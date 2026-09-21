import {StrictMode} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {render as rtlRender, screen, waitFor, within} from '@testing-library/react';
import {QueryClient} from '@tanstack/react-query';
import {renderWithProviders, TestProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {buildExploreSqlHandoff} from '../../lib/routeHandoff';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_MAX, EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {explorationSourceScope, explorerKeys} from './explorerKeys';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationSource, ExplorationTab, ExplorationTabsState} from './dataExplorer.types';
import type {TestRoute} from '../../test/renderWithProviders';

// The Explorer's half of *Explore in Data Explorer*: a statement arrives as router state, opens
// ONE tab, re-runs, and leaves nothing behind in history for a reload or Back to act on again.
// Rendered under `StrictMode` because the app is, and its doubled effects are the hazard — as the
// placed root, since a nested one doubles nothing.

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
const AUTH = authenticated('alice');

const BODY = 'SELECT name, qty FROM db.orders';
const LABEL = 'SELECT name, qty FROM db.order…';
const UNFILTERED = `SELECT *\nFROM (\n${BODY}\n) AS t`;
const FILTERED = `${UNFILTERED}\nWHERE "qty" > 5`;
// Begins with BODY, so a predicate that only looked for the body's text would evict it too.
const OTHER_BODY = `${BODY} WHERE qty > 1`;
const OTHER_UNFILTERED = `SELECT *\nFROM (\n${OTHER_BODY}\n) AS t`;
const ORDERS: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'};
const ORDERS_SQL = 'SELECT *\nFROM "alice"."orders"';

const HANDOFF_ROUTE: TestRoute = {pathname: '/explore', state: buildExploreSqlHandoff({body: BODY, label: LABEL})};

/** A client that keeps everything, so what the test seeds is still there when the page reads it. */
function keepAllClient(): QueryClient {
  return new QueryClient({defaultOptions: {queries: {retry: false, gcTime: Infinity, staleTime: Infinity}}});
}

function executionKey(source: ExplorationSource, sql: string) {
  return explorerKeys.execution(explorationSourceScope(source), sql);
}

function tab(id: string, source: ExplorationSource): ExplorationTab {
  return {
    id,
    label: source.kind === 'table' ? source.table : source.label,
    exploration: newExploration(source, id),
    scannedByExecution: {},
    history: {past: [], future: []}
  };
}

function seedTabs(tabs: ExplorationTab[], activeTabId = tabs[0]?.id ?? '') {
  const state: ExplorationTabsState = {version: 1, tabs, activeTabId};
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

function sqlsRun(): string[] {
  return vi.mocked(runQuery).mock.calls.map(([call]) => (call as {sql: string}).sql);
}

function render(route: TestRoute, queryClient?: QueryClient) {
  return renderWithProviders(<DataExplorerWorkspace />, {
    route,
    auth: AUTH,
    browserRouter: true,
    strictMode: true,
    queryClient
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);
  let seq = 0;
  vi.mocked(runQuery).mockImplementation((async () => {
    seq += 1;
    return ok({queryExecutionId: `exec-${seq}`});
  }) as never);
  vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
    ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})) as never);
  vi.mocked(getQueryResults).mockResolvedValue(
    ok({
      columns: [
        {name: 'name', type: 'string'},
        {name: 'qty', type: 'int'}
      ],
      rows: [['apple', '3']]
    }) as never
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('a statement handed over from a Query result', () => {
  it('opens one tab over it, runs only it, and clears the hand-off from history', async () => {
    // The restored active tab is uncached: running it on the way past would bill a statement
    // nobody sees.
    seedTabs([tab('t1', ORDERS)]);
    const client = keepAllClient();
    const {unmount} = render(HANDOFF_ROUTE, client);

    expect(await screen.findByRole('tab', {name: LABEL})).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(sqlsRun()).toEqual([UNFILTERED]);
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    await waitFor(() => expect(window.history.state).toMatchObject({usr: null}));
    expect(window.location.pathname).toBe('/explore');

    // What a reload looks like: a fresh workspace on the same history and the same session.
    unmount();
    rtlRender(
      <StrictMode>
        <TestProviders
          auth={AUTH}
          browserRouter
          queryClient={client}>
          <DataExplorerWorkspace />
        </TestProviders>
      </StrictMode>
    );
    expect(await screen.findByRole('tab', {name: LABEL})).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    expect(sqlsRun()).toEqual([UNFILTERED]);
  });

  it('re-runs the statement and every filter over it, and leaves another statement’s cache alone', async () => {
    const same: ExplorationSource = {kind: 'sql', body: BODY, label: LABEL};
    const other: ExplorationSource = {kind: 'sql', body: OTHER_BODY, label: 'other'};
    seedTabs([tab('s1', same), tab('s2', other)]);
    const client = keepAllClient();
    client.setQueryData(executionKey(same, UNFILTERED), 'old-unfiltered');
    client.setQueryData(executionKey(same, FILTERED), 'old-filtered');
    client.setQueryData(executionKey(other, OTHER_UNFILTERED), 'old-other');
    const {user} = render(HANDOFF_ROUTE, client);

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(sqlsRun()).toEqual([UNFILTERED]);

    await user.click(await screen.findByRole('button', {name: /^Column options: qty/}));
    await user.click(screen.getByRole('menuitem', {name: 'Filter: greater than…'}));
    await user.type(screen.getByLabelText('Value'), '5');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(sqlsRun()).toEqual([UNFILTERED, FILTERED]);

    // The other statement's execution is still cached, and showing its tab runs nothing.
    expect(client.getQueryData(executionKey(other, OTHER_UNFILTERED))).toBe('old-other');
    await user.click(screen.getByRole('tab', {name: 'other'}));
    await waitFor(() => expect(getQueryStatus).toHaveBeenCalledWith('old-other'));
    expect(sqlsRun()).toEqual([UNFILTERED, FILTERED]);
  });

  it('opens a linked table exactly once when no statement was handed over', async () => {
    render('/explore?space=personal&db=alice&table=orders');

    expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(sqlsRun()).toEqual([ORDERS_SQL]);
    expect(screen.getAllByRole('tab')).toHaveLength(1);
  });

  it('opens a linked table AND a handed-over statement once each, and leaves neither in the URL or state', async () => {
    render({...HANDOFF_ROUTE, search: '?space=personal&db=alice&table=orders'} as TestRoute);

    expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
    expect(await screen.findByRole('tab', {name: LABEL})).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(window.history.state).toMatchObject({usr: null}));
    expect(window.location.search).toBe('');
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(sqlsRun()).toEqual([UNFILTERED]);
  });

  it('opens nothing behind a refused link, and runs nothing', async () => {
    render({...HANDOFF_ROUTE, search: '?space=someone_elses&db=someone_elses&table=orders'} as TestRoute);

    expect(await screen.findByRole('heading', {name: 'You don’t have access to that space'})).toBeInTheDocument();
    expect(runQuery).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`) ?? '').not.toContain(BODY);
  });

  it('at the tab limit, raises the limit dialog, opens and evicts nothing, and still clears history', async () => {
    const tables = Array.from({length: EXPLORATION_TABS_MAX}, (_, index) =>
      tab(`t${index}`, {...ORDERS, table: `table_${index}`})
    );
    seedTabs(tables);
    const same: ExplorationSource = {kind: 'sql', body: BODY, label: LABEL};
    const client = keepAllClient();
    client.setQueryData(executionKey(same, UNFILTERED), 'old-unfiltered');
    render(HANDOFF_ROUTE, client);

    const dialog = await screen.findByRole('alertdialog', {name: 'Exploration limit reached'});
    expect(within(dialog).getByText(/Close one before opening another/)).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(EXPLORATION_TABS_MAX);
    await waitFor(() => expect(window.history.state).toMatchObject({usr: null}));
    expect(client.getQueryData(executionKey(same, UNFILTERED))).toBe('old-unfiltered');
    expect(sqlsRun()).not.toContain(UNFILTERED);
  });
});
