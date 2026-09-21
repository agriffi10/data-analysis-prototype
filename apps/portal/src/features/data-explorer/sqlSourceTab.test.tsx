import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {chooseExplorationOption, explorationOption} from './explorationOptions.testkit';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace, SQL_SOURCE_VIEW_REFUSAL} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {copyObject, listFiles, objectExists} from '../file-browser/fileBrowser.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState} from './dataExplorer.types';

// A tab whose source is a statement rather than a table: no Glue schema, headers from the
// execution's own metadata, and every gesture composed over `(<body>) AS t`.

vi.mock('../catalog/glue.service', () => ({getDatabase: vi.fn(), listTables: vi.fn()}));
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn()
}));
vi.mock('../file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../file-browser/fileBrowser.service')>()),
  listFiles: vi.fn(),
  copyObject: vi.fn(),
  ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
  objectExists: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn()
}));

const ok = <T,>(data: T) => ({success: true as const, data});

const BODY = 'SELECT name, qty FROM db.orders';
const FROM = `FROM (\n${BODY}\n) AS t`;
// Glue's spelling, which is what `getQueryResults` hands back after `normalizeColumnType`.
const COLUMNS = [
  {name: 'name', type: 'string'},
  {name: 'qty', type: 'int'}
];
const ROWS = [
  ['apple', '3'],
  ['pear', '9']
];

const sqlByExecution = new Map<string, string>();

function lastSql(): string {
  const calls = vi.mocked(runQuery).mock.calls;
  return (calls[calls.length - 1][0] as {sql: string}).sql;
}

function storedTabs(): ExplorationTabsState {
  return JSON.parse(sessionStorage.getItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`) ?? 'null') as ExplorationTabsState;
}

function render() {
  return renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
}

async function chooseFromMenu(user: ReturnType<typeof render>['user'], column: string, item: string) {
  await user.click(await screen.findByRole('button', {name: new RegExp(`^Column options: ${column}`)}));
  await user.click(await screen.findByRole('menuitem', {name: item}));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  sqlByExecution.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([]) as never);
  let seq = 0;
  vi.mocked(runQuery).mockImplementation((async ({sql}: {sql: string}) => {
    seq += 1;
    const queryExecutionId = `exec-${seq}`;
    sqlByExecution.set(queryExecutionId, sql);
    return ok({queryExecutionId});
  }) as never);
  vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
    ok({
      queryExecutionId,
      state: 'SUCCEEDED',
      dataScannedBytes: 2048,
      engineExecutionTimeMillis: 120,
      outputLocation: `s3://user-space/alice/athenaresults/${queryExecutionId}.csv`
    })) as never);
  // A grouped statement answers with the grouped shape, so the source's columns are gone from
  // the result exactly as they are in Athena.
  vi.mocked(getQueryResults).mockImplementation((async ({queryExecutionId}: {queryExecutionId: string}) => {
    const sql = sqlByExecution.get(queryExecutionId) ?? '';
    const grouped = /GROUP BY "(\w+)"/.exec(sql);
    return grouped
      ? ok({columns: [{name: grouped[1], type: 'string'}, {name: 'count_all', type: 'bigint'}], rows: [['x', '2']]})
      : ok({columns: COLUMNS, rows: ROWS});
  }) as never);
  vi.mocked(listFiles).mockResolvedValue(ok({files: [], folders: [], nextToken: undefined}) as never);
  vi.mocked(copyObject).mockResolvedValue(ok({destKey: 'alice/out.csv'}) as never);
  vi.mocked(objectExists).mockResolvedValue(ok(false) as never);

  const exploration = newExploration({kind: 'sql', body: BODY, label: 'SELECT name, qty FROM db.order…'}, 's1');
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [
      {
        id: 's1',
        label: 'SELECT name, qty FROM db.order…',
        exploration,
        scannedByExecution: {},
        history: {past: [], future: []}
      }
    ],
    activeTabId: 's1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('a tab whose source is a statement', () => {
  it('draws headers from the execution, picks operators by type, and filters and sorts over the subquery', async () => {
    const {user} = render();

    expect(await screen.findByRole('columnheader', {name: 'name'})).toBeInTheDocument();
    expect(screen.getByRole('columnheader', {name: 'qty'})).toBeInTheDocument();
    expect(vi.mocked(runQuery).mock.calls[0][0].sql).toBe(`SELECT *\n${FROM}`);

    // `int` is a number: no text operators, and a value that reaches the SQL bare.
    await user.click(screen.getByRole('button', {name: /^Column options: qty/}));
    expect(screen.queryByRole('menuitem', {name: 'Filter: contains…'})).not.toBeInTheDocument();
    await user.click(screen.getByRole('menuitem', {name: 'Filter: greater than…'}));
    await user.type(screen.getByLabelText('Value'), '5');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toBe(`SELECT *\n${FROM}\nWHERE "qty" > 5`);

    // The positive control for the absence above: a text column does offer `contains`.
    await user.click(await screen.findByRole('button', {name: /^Column options: name/}));
    expect(screen.getByRole('menuitem', {name: 'Filter: contains…'})).toBeInTheDocument();
    await user.keyboard('{Escape}');

    await chooseFromMenu(user, 'qty', 'Clear filter');
    await waitFor(() => expect(screen.getByRole('button', {name: 'Column options: qty'})).toBeInTheDocument());
    await chooseFromMenu(user, 'name', 'Sort descending');
    await waitFor(() => expect(lastSql()).toBe(`SELECT *\n${FROM}\nORDER BY "name" DESC`));
  });

  it('remembers its columns, so the Grouping panel still lists them while a grouping is applied', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'qty'});
    await waitFor(() => expect(storedTabs().tabs[0].sqlSourceColumns).toEqual(COLUMNS));

    await chooseExplorationOption(user, 'Grouping');
    let panel = screen.getByRole('complementary', {name: 'Grouping'});
    await user.selectOptions(within(panel).getByRole('combobox', {name: 'Column to group by'}), 'name');
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));
    await waitFor(() =>
      expect(lastSql()).toBe(`SELECT "name", COUNT(*) AS "count_all"\n${FROM}\nGROUP BY "name"`)
    );
    await screen.findByRole('columnheader', {name: 'count_all'});

    // Reopened over the GROUPED result, whose columns are `name` and `count_all` — the panel
    // offers the source's instead, which only the remembered list can supply.
    await user.click(within(panel).getByRole('button', {name: 'Close grouping panel'}));
    await chooseExplorationOption(user, 'Grouping');
    panel = screen.getByRole('complementary', {name: 'Grouping'});
    await user.click(within(panel).getByRole('button', {name: 'Remove name from grouping'}));
    const choices = within(within(panel).getByRole('combobox', {name: 'Column to group by'})).getAllByRole('option');
    expect(choices.map((option) => option.textContent)).toEqual(['Add a column…', 'name', 'qty']);

    await user.selectOptions(within(panel).getByRole('combobox', {name: 'Column to group by'}), 'qty');
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));
    await waitFor(() => expect(lastSql()).toBe(`SELECT "qty", COUNT(*) AS "count_all"\n${FROM}\nGROUP BY "qty"`));
    // A grouped execution never overwrites the source's columns with its own.
    expect(storedTabs().tabs[0].sqlSourceColumns).toEqual(COLUMNS);
  });

  it('saves its own execution’s output, and refuses Create view with the reason', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'qty'});

    const createView = await explorationOption(user, 'Create view…');
    expect(createView).toHaveAttribute('aria-disabled', 'true');
    expect(createView).toHaveAttribute('title', SQL_SOURCE_VIEW_REFUSAL);
    await user.keyboard('{Escape}');

    await waitFor(async () =>
      expect(await explorationOption(user, 'Save results to my files')).not.toHaveAttribute('aria-disabled', 'true')
    );
    await chooseExplorationOption(user, 'Save results to my files');
    const dialog = await screen.findByRole('dialog', {name: 'Save results to my files'});
    const name = within(dialog).getByLabelText('File name');
    await user.clear(name);
    await user.type(name, 'out');
    await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

    await waitFor(() => expect(copyObject).toHaveBeenCalledTimes(1));
    expect(vi.mocked(copyObject).mock.calls[0][0]).toMatchObject({sourceKey: 'alice/athenaresults/exec-1.csv'});
    expect(runQuery).toHaveBeenCalledTimes(1);
  });
});
