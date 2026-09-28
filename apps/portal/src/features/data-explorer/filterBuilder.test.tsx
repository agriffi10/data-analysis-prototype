import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {isListing} from './columnValues.testkit';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationQuery, ExplorationTabsState, FilterItem} from './dataExplorer.types';

// Filter rows: conditions and groups built by pointing, staged in a dialog, and applied as ONE
// execution. Driven through the workspace, because the statement, the execution count and the
// history entry are what the dialog's Apply is for.

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

function seedTab(query: Partial<ExplorationQuery>) {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  exploration.query = {...exploration.query, ...query};
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [{id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}}],
    activeTabId: 't1'
  };
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function stored(): {query: ExplorationQuery; past: number} {
  const state = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '{}') as ExplorationTabsState;
  return {query: state.tabs[0].exploration.query, past: state.tabs[0].history.past.length};
}

function lastSql(): string {
  const calls = vi.mocked(runQuery).mock.calls;
  return (calls[calls.length - 1][0] as {sql: string}).sql;
}

/** Renders the workspace, waits for the first rows, and opens Filter rows. */
async function openBuilder() {
  const view = renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
  await screen.findByRole('gridcell', {name: 'NY'});
  expect(runQuery).toHaveBeenCalledTimes(1);
  await view.user.click(screen.getByRole('button', {name: 'Filter rows…'}));
  return {...view, dialog: screen.getByRole('dialog', {name: 'Filter rows'})};
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
    ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})) as never);
  // A values listing answers with its own shape: `[value, row_count, value_count]`.
  vi.mocked(getQueryResults).mockImplementation((async ({queryExecutionId}: {queryExecutionId: string}) =>
    isListing(sqlOf.get(queryExecutionId) ?? '')
      ? ok({
          columns: [
            {name: 'value', type: 'varchar'},
            {name: 'row_count', type: 'bigint'},
            {name: 'value_count', type: 'bigint'}
          ],
          rows: [
            ['EU', '5', '2'],
            ['US', '4', '2']
          ]
        })
      : ok({
          columns: [
            {name: 'state', type: 'varchar'},
            {name: 'region', type: 'varchar'},
            {name: 'qty', type: 'integer'}
          ],
          rows: [['NY', 'EU', '9']]
        })) as never);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('Filter rows', () => {
  it('applies a condition and an any-group as one execution and one history entry', async () => {
    seedTab({});
    const {user, dialog} = await openBuilder();

    await user.click(within(dialog).getByRole('button', {name: 'Add condition'}));
    await user.selectOptions(within(dialog).getByLabelText('Condition 1: column'), 'state');
    await user.type(within(dialog).getByLabelText('Condition 1: value'), 'NY');
    await user.click(within(dialog).getByRole('button', {name: 'Add group'}));
    await user.selectOptions(within(dialog).getByLabelText('Group 1, condition 1: column'), 'region');
    await user.type(within(dialog).getByLabelText('Group 1, condition 1: value'), 'EU');
    await user.click(within(dialog).getByRole('button', {name: 'Add condition to group 1'}));
    await user.selectOptions(within(dialog).getByLabelText('Group 1, condition 2: column'), 'region');
    await user.type(within(dialog).getByLabelText('Group 1, condition 2: value'), 'US');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(`WHERE ("state" = 'NY' AND ("region" = 'EU' OR "region" = 'US'))`);
    expect(stored().past).toBe(1);
  });

  it('refuses an unchosen column, an empty group and an empty pattern where each is, and runs nothing', async () => {
    seedTab({});
    const {user, dialog} = await openBuilder();

    await user.click(within(dialog).getByRole('button', {name: 'Add condition'}));
    await user.click(within(dialog).getByRole('button', {name: 'Add condition'}));
    await user.selectOptions(within(dialog).getByLabelText('Condition 2: column'), 'state');
    await user.selectOptions(within(dialog).getByLabelText('Condition 2: test'), 'like');
    await user.click(within(dialog).getByRole('button', {name: 'Add group'}));
    await user.click(within(dialog).getByRole('button', {name: 'Remove group 1, condition 1'}));
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    expect(within(dialog).getByLabelText('Condition 1: column')).toHaveAccessibleDescription('Choose a column.');
    expect(within(dialog).getByLabelText('Condition 1: column')).toHaveFocus();
    expect(within(dialog).getByLabelText('Condition 2: value')).toHaveAccessibleDescription(
      /Enter the text to match\./
    );
    expect(within(dialog).getByLabelText('Group 1: match')).toHaveAccessibleDescription(
      'Add a condition to this group, or remove the group.'
    );
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('nests one level of groups, alternating their match, and keeps focus inside the dialog', async () => {
    seedTab({});
    const {user, dialog, container} = await openBuilder();

    await user.click(within(dialog).getByRole('button', {name: 'Add condition'}));
    expect(within(dialog).getByLabelText('Condition 1: column')).toHaveFocus();
    await user.click(within(dialog).getByRole('button', {name: 'Add group'}));
    expect(within(dialog).getByLabelText('Group 1: match')).toHaveDisplayValue('any of these');
    await user.click(within(dialog).getByRole('button', {name: 'Add group to group 1'}));
    expect(within(dialog).getByLabelText('Group 1.1: match')).toHaveDisplayValue('all of these');
    expect(within(dialog).queryByRole('button', {name: 'Add group to group 1.1'})).toBeNull();
    expect(within(dialog).getByRole('button', {name: 'Add condition to group 1.1'})).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', {name: 'Remove group 1.1, condition 1'}));
    expect(within(dialog).getByRole('button', {name: 'Add condition to group 1.1'})).toHaveFocus();

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('hands back what it did not change, whole, beside what it did', async () => {
    // A stored field the builder does not show rides on the clean `in` row, a column the result
    // no longer has rides on another, and the legacy expression is never the builder's to touch.
    const list = {column: 'region', operator: 'in', values: ['EU'], valueKind: 'string', includesNull: true};
    const gone: FilterItem = {column: 'gone', operator: '>', value: '5', valueKind: 'number'};
    seedTab({
      filters: [
        {column: 'qty', operator: '>', value: '5', valueKind: 'number'},
        {column: 'qty', operator: '<', value: '10', valueKind: 'number'},
        list as FilterItem,
        gone
      ],
      expression: "state <> 'void'"
    });
    const {user, dialog} = await openBuilder();

    expect(within(dialog).getByLabelText('Condition 4: column')).toHaveDisplayValue('gone');
    // The edited row is the one on the column the result no longer lists, so its type cannot be
    // looked up — it has to keep the numeric kind it was stored with, or `> 6` would be quoted.
    await user.clear(within(dialog).getByLabelText('Condition 4: value'));
    await user.type(within(dialog).getByLabelText('Condition 4: value'), '6');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(
      `WHERE ("qty" > 5 AND "qty" < 10 AND ("region" IN ('EU') OR "region" IS NULL) AND "gone" > 6) AND (state <> 'void')`
    );
    expect(stored().query.filters).toEqual([
      {column: 'qty', operator: '>', value: '5', valueKind: 'number'},
      {column: 'qty', operator: '<', value: '10', valueKind: 'number'},
      list,
      {...gone, value: '6'}
    ]);
  });

  it('runs nothing when a change is cancelled, or when Apply changes nothing', async () => {
    const applied: FilterItem[] = [{column: 'state', operator: '=', value: 'NY', valueKind: 'string'}];
    seedTab({filters: applied});
    const {user, dialog} = await openBuilder();

    await user.click(within(dialog).getByRole('button', {name: 'Remove condition 1'}));
    await user.click(within(dialog).getByRole('button', {name: 'Cancel'}));
    await user.click(screen.getByRole('button', {name: 'Filter rows…'}));
    await user.click(within(screen.getByRole('dialog', {name: 'Filter rows'})).getByRole('button', {name: 'Apply'}));

    expect(screen.queryByRole('dialog', {name: 'Filter rows'})).toBeNull();
    expect(runQuery).toHaveBeenCalledTimes(1);
    expect(stored()).toEqual({query: expect.objectContaining({filters: applied}), past: 0});
  });

  it('clears the filter in one run when every condition is removed', async () => {
    seedTab({filters: [{column: 'state', operator: '=', value: 'NY', valueKind: 'string'}]});
    const {user, dialog} = await openBuilder();

    await user.click(within(dialog).getByRole('button', {name: 'Remove condition 1'}));
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).not.toContain('WHERE');
  });

  it('lists a list row’s values only when asked, unnarrowed, and applies what is ticked', async () => {
    // A top-level `state` condition sits beside the list: the picker must not narrow by it, since
    // inside an OR group a neighbour's narrowing would hide the values the OR exists to reach.
    seedTab({
      filters: [
        {column: 'region', operator: 'in', values: ['EU'], valueKind: 'string'},
        {column: 'state', operator: '=', value: 'NY', valueKind: 'string'}
      ]
    });
    const {user, dialog} = await openBuilder();
    // Mounted is billed, so the picker is not there until asked for — its search field renders the
    // moment it mounts, which makes this absence a check on the mount rather than on the data.
    expect(within(dialog).queryByLabelText('Search values')).toBeNull();

    await user.click(within(dialog).getByRole('button', {name: 'Condition 1: pick values'}));
    await user.click(await within(dialog).findByRole('checkbox', {name: /^US,/}));
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(3));
    const [listing] = vi
      .mocked(runQuery)
      .mock.calls.map(([call]) => (call as {sql: string}).sql)
      .filter(isListing);
    expect(listing).not.toContain('WHERE');
    expect(lastSql()).toContain(`WHERE ("region" IN ('EU', 'US') AND "state" = 'NY')`);
  });
});
