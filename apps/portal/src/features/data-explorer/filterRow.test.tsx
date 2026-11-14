import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {withFakeTimers} from '../../test/fakeTimers';
import {MAX_POLL_DURATION_MS, POLL_INTERVAL_MS} from '../catalog/catalog.constants';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {AwaitingRun, ExplorationQuery, ExplorationTabsState} from './dataExplorer.types';

// The filter row: Filter rows, the chips, and a condition written in SQL kept from before the
// builder. The row stays whatever the results are doing, because a failed apply has to leave the
// user somewhere to correct it — and a stored SQL condition stays on show until the user removes it.

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
const COLUMNS = [
  {name: 'id', type: 'varchar'},
  {name: 'status', type: 'varchar'}
];
const ROWS = [
  ['1', 'open'],
  ['2', 'closed']
];
const STATE_NY = {column: 'state', operator: '=', value: 'NY', valueKind: 'string'} as const;

function seedTab(query: Partial<ExplorationQuery> = {}, awaitingRun?: AwaitingRun) {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  exploration.query = {...exploration.query, ...query};
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [
      {
        id: 't1',
        label: 'orders',
        exploration,
        scannedByExecution: {},
        history: {past: [], future: []},
        ...(awaitingRun ? {awaitingRun} : {})
      }
    ],
    activeTabId: 't1'
  };
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function sqlsRun(): string[] {
  return vi.mocked(runQuery).mock.calls.map(([call]) => (call as {sql: string}).sql);
}

function render(options: {query?: boolean} = {}) {
  return renderWithProviders(
    <DataExplorerWorkspace />,
    {
      route: '/explore',
      path: '/explore',
      routes: {'/query': <p>The Query page</p>},
      auth: authenticated('alice'),
      ...(options.query === false ? {featureFlags: {query: false}} : {})
    }
  );
}

async function filterStatusIsNotNull(user: ReturnType<typeof render>['user']) {
  await user.click(await screen.findByRole('button', {name: /^Column options: status/}));
  await user.click(await screen.findByRole('menuitem', {name: 'Filter: is not null'}));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  window.history.replaceState(null, '', '/');
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
    ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})) as never);
  vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: ROWS}) as never);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('Filter rows is always there', () => {
  it.each([
    {
      state: 'while the first run is still loading',
      arrange: () => vi.mocked(getQueryStatus).mockReturnValue(new Promise(() => {}) as never),
      settle: () => screen.findAllByText('Running…')
    },
    {
      state: 'when the result is empty',
      arrange: () => vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: []}) as never),
      settle: () => screen.findByText('No rows returned.')
    },
    {
      state: 'on a held tab, which runs nothing',
      arrange: () => seedTab({}, {space: 'team', leftOut: {links: 0, patterns: 0}}),
      settle: () => screen.findByRole('button', {name: 'Run'})
    }
  ])('$state', async ({arrange, settle}) => {
    seedTab();
    arrange();

    render();
    await settle();

    expect(screen.getByRole('button', {name: 'Filter rows…'})).toBeInTheDocument();
  });

  it('takes focus when a held tab’s Run leaves with the hold', async () => {
    seedTab({}, {space: 'team', leftOut: {links: 0, patterns: 0}});
    const {user} = render();

    await user.click(await screen.findByRole('button', {name: 'Run'}));

    expect(screen.getByRole('button', {name: 'Filter rows…'})).toHaveFocus();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
  });

  it('keeps the last good rows and the filter row after a failed apply, with the engine’s words closed away', async () => {
    seedTab();
    const {user} = render();
    await screen.findAllByRole('gridcell');
    vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
      queryExecutionId === 'exec-1'
        ? ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})
        : ok({queryExecutionId, state: 'FAILED', stateChangeReason: "line 1:23: mismatched input 'FROM'"})) as never);
    // A failed execution has no results to read, so the fallback is the ONLY way rows can still be
    // on screen — without it the assertion would pass over the failed execution's own rows.
    vi.mocked(getQueryResults).mockImplementation((async ({queryExecutionId}: {queryExecutionId: string}) =>
      queryExecutionId === 'exec-1'
        ? ok({columns: COLUMNS, rows: ROWS})
        : {success: false as const, error: {message: 'Query did not finish successfully'}}) as never);

    await filterStatusIsNotNull(user);

    expect(await screen.findByText(/syntax error in your query/i)).toBeInTheDocument();
    expect(screen.getAllByText(/mismatched input/)[0].closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText('open')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Filter rows…'})).toBeInTheDocument();
    expect(screen.getByRole('list', {name: 'Filters'})).toHaveTextContent('status is not null');
  });

  it('keeps the last good rows under the banner when an apply outlives the ceiling', async () => {
    await withFakeTimers(async () => {
      seedTab();
      const {user} = render();
      await screen.findAllByRole('gridcell');
      vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
        queryExecutionId === 'exec-1'
          ? ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})
          : ok({queryExecutionId, state: 'RUNNING'})) as never);

      await filterStatusIsNotNull(user);
      await waitFor(() => expect(getQueryStatus).toHaveBeenCalledWith('exec-2'));
      // The ceiling's mark in an act of its own, then the one poll whose read decides.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(MAX_POLL_DURATION_MS);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10);
      });

      expect(await screen.findByText(/Data Quarry stopped waiting for this query/)).toBeInTheDocument();
      expect(screen.getByText('open')).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Filter rows…'})).toBeInTheDocument();
    });
  });
});

describe('a condition written in SQL, kept from before the builder', () => {
  it('stays on show and in the statement, which runs once on restore', async () => {
    seedTab({filters: [STATE_NY], expression: "status <> 'void'"});

    render();
    await screen.findAllByRole('gridcell');

    const notice = screen.getByRole('group', {name: 'Condition written in SQL'});
    expect(within(notice).getByText("status <> 'void'")).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(1);
    expect(sqlsRun()[0]).toContain(`WHERE "state" = 'NY' AND (status <> 'void')`);
  });

  it('goes with Remove SQL condition in one run, hands focus to Filter rows, and comes back with Back', async () => {
    seedTab({filters: [STATE_NY], expression: "status <> 'void'"});
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await user.click(screen.getByRole('button', {name: 'Remove SQL condition'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(sqlsRun()[1]).toContain(`WHERE "state" = 'NY'`);
    expect(sqlsRun()[1]).not.toContain('void');
    expect(screen.queryByRole('group', {name: 'Condition written in SQL'})).toBeNull();
    expect(screen.getByRole('button', {name: 'Filter rows…'})).toHaveFocus();
    await user.click(screen.getByRole('button', {name: 'Back to the previous version of this query'}));

    expect(await screen.findByRole('group', {name: 'Condition written in SQL'})).toHaveTextContent("status <> 'void'");
  });

  it('hands the whole statement to Query from the notice’s Open in Query', async () => {
    seedTab({filters: [STATE_NY], expression: "status <> 'void'"});
    const {user, location} = render();
    await screen.findAllByRole('gridcell');
    const notice = screen.getByRole('group', {name: 'Condition written in SQL'});

    await user.click(within(notice).getByRole('button', {name: 'Open in Query'}));

    expect(await screen.findByText('The Query page')).toBeInTheDocument();
    expect((location().state as {openSql: {sql: string}}).openSql.sql).toBe(sqlsRun()[0]);
  });

  it('offers only Remove SQL condition with the query flag off', async () => {
    seedTab({filters: [STATE_NY], expression: "status <> 'void'"});

    render({query: false});
    await screen.findAllByRole('gridcell');

    const notice = screen.getByRole('group', {name: 'Condition written in SQL'});
    expect(within(notice).getByRole('button', {name: 'Remove SQL condition'})).toBeInTheDocument();
    expect(within(notice).queryByRole('button', {name: 'Open in Query'})).toBeNull();
  });
});
