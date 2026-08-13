import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
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

    await user.click(screen.getByRole('button', {name: 'Back to previous filters'}));
    // The unfiltered statement has already run, and the rendered SQL is the cache key —
    // so stepping back is free (AC2).
    await waitFor(() => expect(screen.getByRole('button', {name: /^Column options: status$/})).toBeInTheDocument());
    expect(runQuery).toHaveBeenCalledTimes(2);

    await user.click(screen.getByRole('button', {name: 'Forward to next filters'}));
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
    expect(screen.getByRole('button', {name: 'Back to previous filters'})).toHaveAttribute('title', NO_HISTORY_BACK);
    expect(screen.getByRole('button', {name: 'Forward to next filters'})).toHaveAttribute('title', NO_HISTORY_FORWARD);
  });

  it('holds descriptions with the tab, capped, oldest first out', async () => {
    // One entry short of the cap, each one distinguishable.
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

    await user.click(screen.getByRole('button', {name: 'Back to previous filters'}));
    await waitFor(() => expect(screen.getByLabelText('Filter expression')).toHaveValue(''));

    await user.click(screen.getByRole('button', {name: 'Forward to next filters'}));
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

    await user.click(screen.getByRole('button', {name: 'Remove all filters'}));

    await waitFor(() => expect(screen.getByLabelText('Filter expression')).toHaveValue(''));
    expect(screen.getByRole('button', {name: 'Column options: status'})).toBeInTheDocument();
    // Back to the unfiltered statement, which is still held (AC3).
    expect(runQuery).toHaveBeenCalledTimes(4);
    expect(lastSql()).toContain(`WHERE "status" IS NOT NULL AND (id = '1')`);
  });

  it('says why it is unavailable when there is nothing to clear', async () => {
    render();
    await screen.findAllByRole('gridcell');

    expect(screen.getByRole('button', {name: 'Remove all filters'})).toHaveAttribute(
      'title',
      'There are no filters, expressions or sorts to clear.'
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

  it('says a cache hit is a cache hit, and adds nothing to the total', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'status', 'Filter: is null');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole('button', {name: 'Back to previous filters'}));

    // The stale figure would be TRUE about the execution and false about the gesture:
    // this one scanned nothing at all.
    expect(await screen.findByText(new RegExp(CACHE_HIT_TEXT))).toBeInTheDocument();
    expect(screen.getByText(/4.0 KB scanned by this exploration/)).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(2);
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
