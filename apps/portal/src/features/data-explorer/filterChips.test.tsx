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
import type {ColumnFilter, ExplorationTabsState} from './dataExplorer.types';

// The column filters, shown as chips beside the expression box: what the menus set and the box
// never shows. A chip's remove is one apply, so it is one execution and one history entry, and
// it hands focus on rather than dropping it on the page body.

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
const REMOVE_STATE = 'Remove filter: state equals “NY”';
const REMOVE_QTY = 'Remove filter: qty greater than 5';

function seedTab(query: {filters: ColumnFilter[]; expression?: string}) {
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

describe('the column filter chips', () => {
  it('lists every column filter beside the expression box, in the order they were set', async () => {
    seedTab({filters: [STATE_NY, QTY_OVER_5]});

    await renderSettled();

    const chips = within(screen.getByRole('list', {name: 'Column filters'})).getAllByRole('listitem');
    expect(chips.map((chip) => chip.textContent)).toEqual(['state equals “NY”', 'qty greater than 5']);
  });

  it('removes one filter as one execution and one history entry, and focuses the next chip', async () => {
    seedTab({filters: [STATE_NY, QTY_OVER_5]});
    const {user} = await renderSettled();

    await user.click(screen.getByRole('button', {name: REMOVE_STATE}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(sqlsRun()[1]).toContain('"qty" > 5');
    expect(sqlsRun()[1]).not.toContain('"state"');
    await waitFor(() => expect(persistedPast()).toBe(1));
    expect(screen.getByRole('button', {name: REMOVE_QTY})).toHaveFocus();
  });

  it('focuses the previous chip when the last one goes, and the expression input when none are left', async () => {
    seedTab({filters: [STATE_NY, QTY_OVER_5]});
    const {user} = await renderSettled();

    await user.click(screen.getByRole('button', {name: REMOVE_QTY}));
    expect(await screen.findByRole('button', {name: REMOVE_STATE})).toHaveFocus();
    await user.click(screen.getByRole('button', {name: REMOVE_STATE}));

    expect(screen.queryByRole('list', {name: 'Column filters'})).toBeNull();
    expect(screen.getByLabelText('Filter expression')).toHaveFocus();
  });

  it('brings a removed filter’s chip back with Back', async () => {
    seedTab({filters: [STATE_NY, QTY_OVER_5]});
    const {user} = await renderSettled();
    await user.click(screen.getByRole('button', {name: REMOVE_STATE}));
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1));

    await user.click(screen.getByRole('button', {name: 'Back to previous filters'}));

    const chips = within(screen.getByRole('list', {name: 'Column filters'})).getAllByRole('listitem');
    expect(chips.map((chip) => chip.textContent)).toEqual(['state equals “NY”', 'qty greater than 5']);
  });

  it('shows no chip list for an expression alone', async () => {
    seedTab({filters: [], expression: 'qty > 1'});

    await renderSettled();

    expect(screen.getByLabelText('Filter expression')).toHaveValue('qty > 1');
    expect(screen.queryByRole('list', {name: 'Column filters'})).toBeNull();
  });
});
