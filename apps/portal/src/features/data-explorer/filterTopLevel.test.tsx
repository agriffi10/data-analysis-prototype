import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {chooseExplorationOption} from './explorationOptions.testkit';
import {isListing} from './columnValues.testkit';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState, FilterItem} from './dataExplorer.types';

// The single-filter surfaces — a column's menu, its value dialog, Filter by value…, and Order
// and filter — edit a column's TOP-LEVEL conditions and never reach into a group, and each surface
// that takes a pattern says what its wildcards mean.

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

const QTY_OVER_5: FilterItem = {column: 'qty', operator: '>', value: '5', valueKind: 'number'};
const QTY_OVER_0: FilterItem = {column: 'qty', operator: '>', value: '0', valueKind: 'number'};
const QTY_ONE_OR_OPEN: FilterItem = {
  join: 'or',
  items: [
    {column: 'qty', operator: '=', value: '1', valueKind: 'number'},
    {column: 'status', operator: '=', value: 'open', valueKind: 'string'}
  ]
};
const PATTERN_HINT = /% matches any run of characters and _ matches any one character/;

function seedTab(filters: FilterItem[]) {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  exploration.query = {...exploration.query, filters};
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [{id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}}],
    activeTabId: 't1'
  };
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function storedFilters(): FilterItem[] {
  return (JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '{}') as ExplorationTabsState).tabs[0].exploration.query
    .filters;
}

function lastSql(): string {
  const calls = vi.mocked(runQuery).mock.calls;
  return (calls[calls.length - 1][0] as {sql: string}).sql;
}

async function renderSettled() {
  const view = renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
  await screen.findAllByRole('gridcell');
  expect(runQuery).toHaveBeenCalledTimes(1);
  return view;
}

async function openMenu(user: Awaited<ReturnType<typeof renderSettled>>['user'], column: string) {
  await user.click(await screen.findByRole('button', {name: new RegExp(`^Column options: ${column}`)}));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);
  const sqlOf = new Map<string, string>();
  vi.mocked(runQuery).mockImplementation((async ({sql}: {sql: string}) => {
    const queryExecutionId = `exec-${sqlOf.size + 1}`;
    sqlOf.set(queryExecutionId, sql);
    return ok({queryExecutionId});
  }) as never);
  vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
    ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})) as never);
  // A values listing answers with its own shape: `[value, row_count, value_count]`.
  vi.mocked(getQueryResults).mockImplementation((async ({queryExecutionId}: {queryExecutionId: string}) =>
    isListing(sqlOf.get(queryExecutionId) ?? '')
      ? ok({
          columns: [
            {name: 'value', type: 'integer'},
            {name: 'row_count', type: 'bigint'},
            {name: 'value_count', type: 'bigint'}
          ],
          // Two values, so ticking one is a filter: every value ticked clears the column's filter.
          rows: [
            ['7', '1', '2'],
            ['9', '1', '2']
          ]
        })
      : ok({
          columns: [
            {name: 'qty', type: 'integer'},
            {name: 'status', type: 'varchar'},
            {name: 'name', type: 'varchar'}
          ],
          rows: [['7', 'open', 'Acme']]
        })) as never);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the column menu edits the top level only', () => {
  it('replaces the column’s top-level condition and leaves the group it is also in', async () => {
    seedTab([QTY_OVER_5, QTY_ONE_OR_OPEN]);
    const {user} = await renderSettled();

    await openMenu(user, 'qty');
    await user.click(screen.getByRole('menuitem', {name: 'Filter: equals…'}));
    // Pre-filled from the column's one top-level condition, as an edit rather than a retype.
    expect(screen.getByLabelText('Value')).toHaveValue('5');
    await user.clear(screen.getByLabelText('Value'));
    await user.type(screen.getByLabelText('Value'), '7');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(storedFilters()).toEqual([QTY_ONE_OR_OPEN, {column: 'qty', operator: '=', value: '7', valueKind: 'number'}]);
    expect(lastSql()).toContain(`WHERE (("qty" = 1 OR "status" = 'open') AND "qty" = 7)`);
  });

  it('clears only the top-level condition, then refuses to reach into the group, still marked filtered', async () => {
    seedTab([QTY_OVER_5, QTY_ONE_OR_OPEN]);
    const {user} = await renderSettled();
    await openMenu(user, 'qty');

    await user.click(screen.getByRole('menuitem', {name: 'Clear filter'}));

    await waitFor(() => expect(storedFilters()).toEqual([QTY_ONE_OR_OPEN]));
    const trigger = await screen.findByRole('button', {name: /^Column options: qty, filtered/});
    expect(trigger).toHaveTextContent('•');
    await user.click(trigger);
    expect(screen.getByRole('menuitem', {name: 'Clear filter'})).toHaveAttribute(
      'title',
      'This column’s conditions are inside a group — change them in Filter rows.'
    );
  });

  it('leaves one top-level condition from Filter by value… on a column that had two', async () => {
    seedTab([QTY_OVER_5, QTY_OVER_0]);
    const {user} = await renderSettled();
    await user.click(screen.getAllByRole('gridcell')[0]);
    await chooseExplorationOption(user, 'Filter by value…');
    const dialog = await screen.findByRole('dialog', {name: 'Filter qty by value'});
    await within(dialog).findByText('7');

    await user.click(within(dialog).getByRole('button', {name: 'Apply filter'}));

    await waitFor(() =>
      expect(storedFilters()).toEqual([{column: 'qty', operator: 'in', values: ['7'], valueKind: 'number'}])
    );
  });
});

describe('Order and filter over several conditions', () => {
  it('shows a note for a column with two, and an apply elsewhere keeps both and the group', async () => {
    const list: FilterItem = {column: 'qty', operator: 'in', values: ['1', '2'], valueKind: 'number'};
    seedTab([list, QTY_OVER_0, QTY_ONE_OR_OPEN]);
    const {user} = await renderSettled();
    await chooseExplorationOption(user, 'Order and filter');
    const dialog = await screen.findByRole('dialog', {name: 'Order and filter'});
    expect(within(dialog).getByText('2 conditions — change them in Filter rows')).toBeInTheDocument();

    await user.selectOptions(within(dialog).getByLabelText('Sort status'), 'asc');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(storedFilters()).toEqual([list, QTY_OVER_0, QTY_ONE_OR_OPEN]);
  });
});

describe('a pattern, wherever it is typed', () => {
  it('is explained under the value dialog’s field for is like, and refused there when empty', async () => {
    seedTab([]);
    const {user} = await renderSettled();
    await openMenu(user, 'name');
    await user.click(screen.getByRole('menuitem', {name: 'Filter: is like…'}));

    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    expect(screen.getByLabelText('Value')).toHaveAccessibleDescription(PATTERN_HINT);
    expect(screen.getByLabelText('Value')).toHaveAccessibleDescription(/Enter the text to match\./);
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('is explained in Order and filter for is not like only, and refused there when empty', async () => {
    seedTab([{column: 'name', operator: 'contains', value: 'Ac', valueKind: 'string'}]);
    const {user} = await renderSettled();
    await chooseExplorationOption(user, 'Order and filter');
    const dialog = await screen.findByRole('dialog', {name: 'Order and filter'});
    expect(within(dialog).getByLabelText('Value for name')).not.toHaveAccessibleDescription(PATTERN_HINT);
    await user.selectOptions(within(dialog).getByLabelText('Filter name'), 'notLike');
    await user.clear(within(dialog).getByLabelText('Value for name'));

    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    expect(within(dialog).getByLabelText('Value for name')).toHaveAccessibleDescription(PATTERN_HINT);
    expect(within(dialog).getByLabelText('Value for name')).toHaveAccessibleDescription(/Enter the text to match\./);
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('reads as is like on its chip', async () => {
    seedTab([{column: 'name', operator: 'like', value: 'A%B', valueKind: 'string'}]);

    await renderSettled();

    expect(screen.getByRole('list', {name: 'Filters'})).toHaveTextContent('name is like “A%B”');
    expect(lastSql()).toContain(`WHERE lower("name") LIKE lower('A%B')`);
  });
});
