import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ColumnFilter, ExplorationTabsState, FilterItem} from './dataExplorer.types';

// The applied filter, shown as chips beside Filter rows: one per top-level item, a group worded in
// the brackets its statement carries. A chip's remove is one apply, so it is one execution and one
// history entry, and it hands focus on rather than dropping it on the page body.

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

const STATE_NY: ColumnFilter = {column: 'state', operator: '=', value: 'NY', valueKind: 'string'};
const QTY_OVER_5: ColumnFilter = {column: 'qty', operator: '>', value: '5', valueKind: 'number'};
const CITY_SET: ColumnFilter = {column: 'city', operator: 'isNotNull'};
const REMOVE_STATE = 'Remove filter: state equals “NY”';
const REMOVE_QTY = 'Remove filter: qty greater than 5';
const REMOVE_CITY = 'Remove filter: city is not null';
const EU_OR_US: FilterItem = {
  join: 'or',
  items: [
    {column: 'region', operator: '=', value: 'EU', valueKind: 'string'},
    {column: 'region', operator: '=', value: 'US', valueKind: 'string'}
  ]
};
const EU_OR_US_LABEL = '(region equals “EU” or region equals “US”)';

function seedTab(query: {filters: FilterItem[]; expression?: string}) {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  exploration.query = {...exploration.query, filters: query.filters, expression: query.expression ?? null};
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [{id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}}],
    activeTabId: 't1'
  };
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function sqlsRun(): string[] {
  return vi.mocked(runQuery).mock.calls.map(([call]) => (call as {sql: string}).sql);
}

function persistedPast(): number {
  const state = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '{}') as ExplorationTabsState;
  return state.tabs[0].history.past.length;
}

/** Renders the workspace and waits for the seeded tab's first rows, so a later count starts at one. */
async function renderSettled() {
  const view = renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
  await screen.findByRole('gridcell', {name: 'NY'});
  expect(runQuery).toHaveBeenCalledTimes(1);
  return view;
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
        {name: 'state', type: 'varchar'},
        {name: 'qty', type: 'integer'}
      ],
      rows: [['NY', '9']]
    }) as never
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the filter chips', () => {
  it('lists every top-level item, a group in its brackets, in the order they were set', async () => {
    seedTab({filters: [STATE_NY, EU_OR_US, QTY_OVER_5]});

    await renderSettled();

    const chips = within(screen.getByRole('list', {name: 'Filters'})).getAllByRole('listitem');
    expect(chips.map((chip) => chip.textContent)).toEqual(['state equals “NY”', EU_OR_US_LABEL, 'qty greater than 5']);
  });

  it('removes a whole group as one execution and one history entry, and focuses the next chip', async () => {
    seedTab({filters: [STATE_NY, EU_OR_US, QTY_OVER_5]});
    const {user} = await renderSettled();

    await user.click(screen.getByRole('button', {name: `Remove filter: ${EU_OR_US_LABEL}`}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(sqlsRun()[1]).toContain(`WHERE ("state" = 'NY' AND "qty" > 5)`);
    await waitFor(() => expect(persistedPast()).toBe(1));
    expect(screen.getByRole('button', {name: REMOVE_QTY})).toHaveFocus();
  });

  it('hands focus by position to the next chip, else the previous one, else Filter rows', async () => {
    // Two chips read alike here, so a focus found by LABEL would land on the first of them.
    seedTab({filters: [STATE_NY, QTY_OVER_5, STATE_NY, CITY_SET]});
    const {user} = await renderSettled();

    await user.click(screen.getByRole('button', {name: REMOVE_QTY}));
    await waitFor(() => expect(screen.getAllByRole('button', {name: REMOVE_STATE})[1]).toHaveFocus());
    await user.click(screen.getByRole('button', {name: REMOVE_CITY}));
    await waitFor(() => expect(screen.getAllByRole('button', {name: REMOVE_STATE})[1]).toHaveFocus());
    await user.click(screen.getAllByRole('button', {name: REMOVE_STATE})[1]);
    await waitFor(() => expect(screen.getByRole('button', {name: REMOVE_STATE})).toHaveFocus());
    await user.click(screen.getByRole('button', {name: REMOVE_STATE}));

    await waitFor(() => expect(screen.getByRole('button', {name: 'Filter rows…'})).toHaveFocus());
    expect(screen.queryByRole('list', {name: 'Filters'})).toBeNull();
  });

  it('brings a removed filter’s chip back with Back', async () => {
    seedTab({filters: [STATE_NY, QTY_OVER_5]});
    const {user} = await renderSettled();
    await user.click(screen.getByRole('button', {name: REMOVE_STATE}));
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1));

    await user.click(screen.getByRole('button', {name: 'Back to the previous version of this query'}));

    const chips = within(screen.getByRole('list', {name: 'Filters'})).getAllByRole('listitem');
    expect(chips.map((chip) => chip.textContent)).toEqual(['state equals “NY”', 'qty greater than 5']);
  });
});
