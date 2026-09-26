import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {createTestQueryClient, renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {chooseExplorationOption, explorationOption} from './explorationOptions.testkit';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX, EXPLORER_FILTER_HISTORY_MAX} from './dataExplorer.constants';
import {emptyExplorationQuery, newExploration} from './exploration';
import {CACHE_HIT_TEXT} from './CostIndicator';
import {NO_HISTORY_BACK, NO_HISTORY_FORWARD} from './FilterHistoryControls';
import {SUSPENDED_TEXT} from './ExplorationResultsRegion';
import {filterValueKind, isEmptyQuery, moveSortPriority, sameQuery, setSort, sortOf} from './explorationQueryOps';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {MAX_POLL_DURATION_MS, POLL_INTERVAL_MS} from '../catalog/catalog.constants';
import {withFakeTimers} from '../../test/fakeTimers';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationQuery, ExplorationTabsState} from './dataExplorer.types';

// SPEC-181 FR-006, FR-007 and FR-008: the per-tab description history, Remove all, and
// what every apply is reported to have cost.

vi.mock('../catalog/glue.service', () => ({
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));
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

const COLUMNS = [
  {name: 'id', type: 'varchar'},
  {name: 'status', type: 'varchar'}
];
const ROWS = [
  ['1', 'open'],
  ['2', 'closed']
];

function lastSql(): string {
  const calls = vi.mocked(runQuery).mock.calls;
  return (calls[calls.length - 1][0] as {sql: string}).sql;
}

function render() {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
  return {user};
}

function seedTab(history: {past: ExplorationQuery[]; future: ExplorationQuery[]} = {past: [], future: []}) {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [{id: 't1', label: 'orders', exploration, scannedByExecution: {}, history}],
    activeTabId: 't1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

function storedHistory() {
  const raw = sessionStorage.getItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`) ?? '{}';
  return (JSON.parse(raw) as ExplorationTabsState).tabs[0].history;
}

async function chooseFromMenu(user: ReturnType<typeof userEvent.setup>, column: string, item: string) {
  await user.click(await screen.findByRole('button', {name: new RegExp(`^Column options: ${column}`)}));
  await user.click(await screen.findByRole('menuitem', {name: item}));
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
  vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: ROWS}) as never);
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ─── FR-006: filter history ──────────────────────────────────────────────────

describe('filter history', () => {
  it('steps back and forward through descriptions, from cache', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'status', 'Filter: is not null');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole('button', {name: 'Back to the previous version of this query'}));
    // The unfiltered statement has already run, and the rendered SQL is the cache key —
    // so stepping back is free (AC2).
    await waitFor(() => expect(screen.getByRole('button', {name: /^Column options: status$/})).toBeInTheDocument());
    expect(runQuery).toHaveBeenCalledTimes(2);

    await user.click(screen.getByRole('button', {name: 'Forward to the next version of this query'}));
    await waitFor(() =>
      expect(screen.getByRole('button', {name: 'Column options: status, filtered'})).toBeInTheDocument()
    );
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('says why each control is unavailable rather than vanishing', async () => {
    render();
    await screen.findAllByRole('gridcell');

    // `aria-disabled`, not `disabled` (SPEC-172): the control keeps its place in the tab
    // order and the reason is reachable.
    expect(screen.getByRole('button', {name: 'Back to the previous version of this query'})).toHaveAttribute(
      'title',
      NO_HISTORY_BACK
    );
    expect(screen.getByRole('button', {name: 'Forward to the next version of this query'})).toHaveAttribute(
      'title',
      NO_HISTORY_FORWARD
    );
  });

  it('holds descriptions with the tab, capped, oldest first out', async () => {
    // Exactly the cap, each entry distinguishable, so one more must push one off.
    const past = Array.from({length: EXPLORER_FILTER_HISTORY_MAX}, (_, i) => ({
      ...emptyExplorationQuery(),
      expression: `seeded ${i}`
    }));
    seedTab({past, future: []});
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'status', 'Filter: is null');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    const stored = storedHistory();
    expect(stored.past).toHaveLength(EXPLORER_FILTER_HISTORY_MAX);
    expect(stored.past[0].expression).toBe('seeded 1'); // `seeded 0` fell off the end
    // Descriptions, never result sets (AC5) — the whole cursor is JSON in the tab.
    expect(JSON.stringify(stored)).not.toContain('open');
  });

  it('looks again at a statement the watch stopped waiting for when history returns to it', async () => {
    await withFakeTimers(async () => {
      // Keeps the cache: collected on the way out, exec-1 would be asked about again whatever the
      // hook remembered, and the test would not see a watch that failed to start over.
      const queryClient = createTestQueryClient();
      queryClient.setDefaultOptions({queries: {...queryClient.getDefaultOptions().queries, gcTime: Infinity}});
      vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
        queryExecutionId === 'exec-1'
          ? ok({queryExecutionId, state: 'RUNNING'})
          : ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})) as never);
      const requestsFor = (id: string) => vi.mocked(getQueryStatus).mock.calls.filter(([asked]) => asked === id).length;
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice'), queryClient});
      try {
        await waitFor(() => expect(getQueryStatus).toHaveBeenCalledWith('exec-1'));
        // The ceiling's mark in an act of its own, then the one poll whose read decides.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(MAX_POLL_DURATION_MS);
        });
        await act(async () => {
          await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10);
        });

        await screen.findByText(/Data Quarry stopped waiting for this query/);

        await user.type(screen.getByLabelText('Filter expression'), "status = 'open'{Enter}");
        await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
        await screen.findAllByRole('gridcell');
        const beforeReturning = requestsFor('exec-1');

        await user.click(screen.getByRole('button', {name: 'Back to the previous version of this query'}));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10);
        });

        expect(screen.queryByText(SUSPENDED_TEXT)).not.toBeInTheDocument();
        expect(requestsFor('exec-1')).toBeGreaterThan(beforeReturning);
        expect(screen.queryByText(/Data Quarry stopped waiting for this query/)).not.toBeInTheDocument();
        // The cached execution, watched again: going back is not a second bill.
        expect(runQuery).toHaveBeenCalledTimes(2);
      } finally {
        queryClient.clear();
      }
    });
  });

  it('never re-runs a statement that already failed; it restores and waits', async () => {
    vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
      queryExecutionId === 'exec-2'
        ? ok({queryExecutionId, state: 'FAILED', stateChangeReason: 'mismatched input'})
        : ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})) as never);
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await user.type(screen.getByLabelText('Filter expression'), 'not sql at all{Enter}');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    await screen.findByText(/syntax error in your query/i);

    await user.click(screen.getByRole('button', {name: 'Back to the previous version of this query'}));
    await waitFor(() => expect(screen.getByLabelText('Filter expression')).toHaveValue(''));

    await user.click(screen.getByRole('button', {name: 'Forward to the next version of this query'}));
    // The description is restored — the text is back in the bar — and nothing has run.
    expect(await screen.findByText(SUSPENDED_TEXT)).toBeInTheDocument();
    expect(screen.getByLabelText('Filter expression')).toHaveValue('not sql at all');
    expect(runQuery).toHaveBeenCalledTimes(2);

    // The retry is the USER's (AC4).
    await user.click(screen.getByRole('button', {name: 'Run it anyway'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(3));
  });
});

// ─── FR-007: remove all ──────────────────────────────────────────────────────

describe('remove all', () => {
  it('clears filters, the expression and every sort in ONE apply, from cache', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'status', 'Sort ascending');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    await chooseFromMenu(user, 'status', 'Filter: is not null');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(3));
    await user.type(screen.getByLabelText('Filter expression'), "id = '1'{Enter}");
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(4));

    await chooseExplorationOption(user, 'Remove all filters and sorts');

    await waitFor(() => expect(screen.getByLabelText('Filter expression')).toHaveValue(''));
    expect(screen.getByRole('button', {name: 'Column options: status'})).toBeInTheDocument();
    // Back to the unfiltered statement, which is still held (AC3).
    expect(runQuery).toHaveBeenCalledTimes(4);
    expect(lastSql()).toContain(`WHERE "status" IS NOT NULL AND (id = '1')`);
  });

  it('says why it is unavailable when there is nothing to clear', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    // The grouping is named too, from SPEC-182: it is one of the things this clears.
    expect(await explorationOption(user, 'Remove all filters and sorts')).toHaveAttribute(
      'title',
      'There are no filters, expressions, sorts or grouping to clear.'
    );
  });
});

// ─── FR-008: cost on every apply ─────────────────────────────────────────────

describe('cost reporting', () => {
  it('reports what this execution scanned, and the tab’s running total', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    expect(
      await screen.findByText(/This query scanned 2.0 KB · 2.0 KB scanned by this exploration/)
    ).toBeInTheDocument();

    await chooseFromMenu(user, 'status', 'Filter: is null');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByText(/This query scanned 2.0 KB · 4.0 KB scanned by this exploration/)
    ).toBeInTheDocument();
  });

  it('reports the FINAL figure, not the first poll’s absent statistics', async () => {
    // A QUEUED/RUNNING poll carries no `Statistics` and so reports a perfectly confident
    // 0 B. Every real query takes more than one poll, and the per-apply figure is captured
    // ONCE per execution (deliberately — a cache hit has to be read before the ledger is
    // written), so a fixture that succeeds on the first poll hid a surface permanently
    // reading "This query scanned 0 B" beside a total that disagreed with it.
    const polled = new Set<string>();
    vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) => {
      if (!polled.has(queryExecutionId)) {
        polled.add(queryExecutionId);
        return ok({queryExecutionId, state: 'RUNNING'});
      }
      return ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048});
    }) as never);
    render();

    expect(await screen.findByText(/This query scanned 2.0 KB/, {}, {timeout: 10_000})).toBeInTheDocument();
    expect(screen.queryByText(/scanned 0 B/)).not.toBeInTheDocument();
  }, 15_000);

  it('says a cache hit is a cache hit, and adds nothing to the total', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'status', 'Filter: is null');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole('button', {name: 'Back to the previous version of this query'}));

    // The stale figure would be TRUE about the execution and false about the gesture:
    // this one scanned nothing at all.
    expect(await screen.findByText(new RegExp(CACHE_HIT_TEXT))).toBeInTheDocument();
    expect(screen.getByText(/4.0 KB scanned by this exploration/)).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('never shows another tab’s figure while this tab’s own run has not reported', async () => {
    seedTwoTabs();
    vi.mocked(listTables).mockResolvedValue(
      ok([
        {name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []},
        {name: 'invoices', tableType: 'EXTERNAL_TABLE', columns: []}
      ]) as never
    );
    const sqlById = new Map<string, string>();
    let seq = 0;
    vi.mocked(runQuery).mockImplementation((async ({sql}: {sql: string}) => {
      seq += 1;
      sqlById.set(`exec-${seq}`, sql);
      return ok({queryExecutionId: `exec-${seq}`});
    }) as never);
    vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
      (sqlById.get(queryExecutionId) ?? '').includes('invoices')
        ? ok({queryExecutionId, state: 'RUNNING'})
        : ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})) as never);
    const {user} = render();
    await screen.findByText(/This query scanned 2.0 KB/);

    await user.click(screen.getByRole('tab', {name: /invoices/}));

    expect(await screen.findByText(/^0 B scanned by this exploration$/)).toBeInTheDocument();
    expect(screen.queryByText(/This query scanned 2.0 KB/)).not.toBeInTheDocument();
  });
});

// ─── The pure edits underneath all of it ─────────────────────────────────────

describe('the query operations', () => {
  it('reads a numeric column’s kind from its type, in either dialect’s spelling', () => {
    // `useSourceColumns` normalises Glue's names; an execution's own metadata arrives raw
    // from Athena, so both spellings reach this function.
    expect(filterValueKind('bigint')).toBe('number');
    expect(filterValueKind('integer')).toBe('number');
    expect(filterValueKind('int')).toBe('number');
    expect(filterValueKind('decimal(10,2)')).toBe('number');
    expect(filterValueKind('varchar')).toBe('string');
    expect(filterValueKind('string')).toBe('string');
    expect(filterValueKind('timestamp')).toBe('string');
    // Unknown types quote, which is the SAFE direction: a quoted value is escaped and a
    // type mismatch is a readable query error; emitting bare would be neither.
    expect(filterValueKind('map<string,int>')).toBe('string');
  });

  it('compares two descriptions by what they would RENDER, not by array order', () => {
    const a = setSort(setSort(emptyExplorationQuery(), 'b', 'asc'), 'a', 'desc');
    const b = {...a, ordering: [...a.ordering].reverse()};
    expect(sameQuery(a, b)).toBe(true);
    expect(sameQuery(a, setSort(a, 'a', 'asc'))).toBe(false);
    expect(isEmptyQuery(emptyExplorationQuery())).toBe(true);
    expect(isEmptyQuery({...emptyExplorationQuery(), expression: '   '})).toBe(true);
  });

  it('moves a sort by array position, not by the priority it already carries', () => {
    const query = setSort(setSort(setSort(emptyExplorationQuery(), 'a', 'asc'), 'b', 'asc'), 'c', 'asc');
    const moved = moveSortPriority(query, 'c', -1);
    expect(sortOf(moved, 'c')?.position).toBe(2);
    expect(sortOf(moved, 'b')?.position).toBe(3);
    // Off the end is a no-op rather than a throw or a silent wrap.
    expect(moveSortPriority(query, 'a', -1)).toBe(query);
  });
});

// Two tabs over DIFFERENT tables, so "whose rows are these?" is answerable. The failing
// statement is the one carrying `bad`: its execution FAILS and its results cannot be read,
// which is what a real Athena failure looks like from here.
const SQL_BY_EXECUTION = new Map<string, string>();

function seedTwoTabs() {
  const orders = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  const invoices = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'invoices'}, 't2');
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [
      {id: 't1', label: 'orders', exploration: orders, scannedByExecution: {}, history: {past: [], future: []}},
      {id: 't2', label: 'invoices', exploration: invoices, scannedByExecution: {}, history: {past: [], future: []}}
    ],
    activeTabId: 't1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

function mockTwoTables() {
  SQL_BY_EXECUTION.clear();
  let seq = 0;
  vi.mocked(runQuery).mockImplementation((async ({sql}: {sql: string}) => {
    seq += 1;
    const queryExecutionId = `exec-${seq}`;
    SQL_BY_EXECUTION.set(queryExecutionId, sql);
    return ok({queryExecutionId});
  }) as never);
  vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
    (SQL_BY_EXECUTION.get(queryExecutionId) ?? '').includes('bad')
      ? ok({queryExecutionId, state: 'FAILED', stateChangeReason: 'mismatched input'})
      : ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})) as never);
  vi.mocked(getQueryResults).mockImplementation((async ({queryExecutionId}: {queryExecutionId: string}) => {
    const sql = SQL_BY_EXECUTION.get(queryExecutionId) ?? '';
    if (sql.includes('bad')) return {success: false as const, error: {message: 'Query did not finish successfully'}};
    return sql.includes('invoices')
      ? ok({columns: COLUMNS, rows: [['9', 'paid']]})
      : ok({columns: COLUMNS, rows: [['1', 'open']]});
  }) as never);
}

describe('across tabs', () => {
  it('does not suspend a tab that never failed', async () => {
    seedTwoTabs();
    mockTwoTables();
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
    await screen.findByText('open');

    await user.type(screen.getByLabelText('Filter expression'), 'bad{Enter}');
    await screen.findByText(/syntax error in your query/i);
    await user.click(screen.getByRole('button', {name: 'Back to the previous version of this query'}));
    await user.click(screen.getByRole('button', {name: 'Forward to the next version of this query'}));
    expect(await screen.findByText(SUSPENDED_TEXT)).toBeInTheDocument();

    // The suspension belongs to the tab that was suspended. Held across the switch, this
    // tab would run nothing and claim a set of filters had failed that never had.
    await user.click(screen.getByRole('tab', {name: /invoices/}));
    await waitFor(() => expect(screen.queryByText(SUSPENDED_TEXT)).not.toBeInTheDocument());
    expect(await screen.findByText('paid')).toBeInTheDocument();
  });

  it('keeps a suspended tab suspended when the user comes back to it', async () => {
    seedTwoTabs();
    mockTwoTables();
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
    await screen.findByText('open');
    await user.type(screen.getByLabelText('Filter expression'), 'bad{Enter}');
    await screen.findByText(/syntax error in your query/i);
    await user.click(screen.getByRole('button', {name: 'Back to previous filters'}));
    await user.click(screen.getByRole('button', {name: 'Forward to next filters'}));
    await screen.findByText(SUSPENDED_TEXT);
    const badStarts = () => vi.mocked(runQuery).mock.calls.filter(([{sql}]) => sql.includes('bad')).length;
    const before = badStarts();

    await user.click(screen.getByRole('tab', {name: /invoices/}));
    await screen.findByText('paid');
    await user.click(screen.getByRole('tab', {name: /orders/}));

    // The round trip is not the user asking for the failed statement again.
    expect(await screen.findByText(SUSPENDED_TEXT)).toBeInTheDocument();
    expect(badStarts()).toBe(before);
  });

  it('never falls back to ANOTHER tab’s rows', async () => {
    seedTwoTabs();
    mockTwoTables();
    // The invoices tab's FIRST execution fails, so it has no good execution of its own —
    // which is the only shape that exposes an unscoped fallback. A tab that has already
    // succeeded falls back to its own execution whether the fallback is scoped or not.
    vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
      (SQL_BY_EXECUTION.get(queryExecutionId) ?? '').includes('invoices')
        ? ok({queryExecutionId, state: 'FAILED', stateChangeReason: 'mismatched input'})
        : ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})) as never);
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
    await screen.findByText('open');

    await user.click(screen.getByRole('tab', {name: /invoices/}));
    await screen.findByText(/syntax error in your query/i);

    // Unscoped, the invoices tab drew the ORDERS table's rows under its own error banner —
    // a grid of another table's data, labelled with this tab's name.
    expect(screen.queryByText('open')).not.toBeInTheDocument();
  });
});
