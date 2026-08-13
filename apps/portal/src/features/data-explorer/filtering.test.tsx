import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {NUMERIC_VALUE_REFUSAL} from './FilterValueDialog';
import {UNFILTERABLE_VALUE} from './ExplorationResultsRegion';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState} from './dataExplorer.types';

// SPEC-181 FR-001 and FR-002: the per-column header menu, and filtering by the focused
// cell's value. Every assertion here is about the SQL that reaches Athena and about how
// many times it reaches it — a filter is a bill, so "exactly one execution" is a claim in
// its own right.

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

// `total amount` is deliberately NOT catalog-safe: column names are quoted, never validated
// against `CATALOG_IDENTIFIER_RE`, which describes the names this app CREATES (FR-001 AC4).
const COLUMNS = [
  {name: 'id', type: 'varchar'},
  {name: 'note', type: 'varchar'},
  {name: 'total amount', type: 'double'}
];
// Row 1 carries the whole interpolation hazard, arriving from data rather than a keyboard.
const ROWS = [
  ['1', "O'Brien", '9.99'],
  ['2', null, '12.50'],
  ['3', 'third', '3.25']
];

const sqlByExecution = new Map<string, string>();

/** The statement of the most recent `StartQueryExecution`. */
function lastSql(): string {
  const calls = vi.mocked(runQuery).mock.calls;
  return (calls[calls.length - 1][0] as {sql: string}).sql;
}

function render() {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
  return {user};
}

function seedTab() {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [{id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}}],
    activeTabId: 't1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

/** Opens one column's menu and chooses an item by its exact label. */
async function chooseFromMenu(user: ReturnType<typeof userEvent.setup>, column: string, item: string) {
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
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);

  let seq = 0;
  vi.mocked(runQuery).mockImplementation((async ({sql}: {sql: string}) => {
    seq += 1;
    const queryExecutionId = `exec-${seq}`;
    sqlByExecution.set(queryExecutionId, sql);
    return ok({queryExecutionId});
  }) as never);
  vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
    ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})) as never);
  // A filtered statement returns the one matching row, so "the query succeeds and returns
  // the matching row" is observable rather than asserted about the string alone.
  vi.mocked(getQueryResults).mockImplementation((async ({queryExecutionId}: {queryExecutionId: string}) => {
    const sql = sqlByExecution.get(queryExecutionId) ?? '';
    return ok({columns: COLUMNS, rows: sql.includes('WHERE') ? [ROWS[0]] : ROWS});
  }) as never);
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ─── FR-001: the per-column header menu ──────────────────────────────────────

describe('the column header menu', () => {
  it('renders a value through sqlLiteral, so a single quote is a value and not a quote', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: equals…');
    await user.type(screen.getByLabelText('Value'), "O'Brien");
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    // Doubled, per the Trino/DML rule — the Hive backslash form would render a literal
    // backslash into the value and match nothing, silently.
    expect(lastSql()).toContain(`WHERE "note" = 'O''Brien'`);
    // Applying from the menu mints EXACTLY one execution (AC5).
    expect(runQuery).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(2)); // header + the match
    expect(screen.getByText("O'Brien")).toBeInTheDocument();
  });

  it('quotes a column name that could never be a catalog identifier, and does not validate it', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'total amount', 'Filter: greater than…');
    await user.type(screen.getByLabelText('Value'), '5');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    // The identifier is quoted; the value is BARE because the column is a double, and
    // `"total amount" > '5'` is a Trino type error rather than a comparison.
    expect(lastSql()).toContain(`WHERE "total amount" > 5`);
  });

  it('refuses a non-numeric value for a numeric column at the input, not at the renderer', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'total amount', 'Filter: equals…');
    await user.type(screen.getByLabelText('Value'), 'lots');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    // The renderer's own refusal names a column and an operator, which SPEC-106 forbids
    // showing anyone — so nothing may reach it.
    expect(await screen.findByText(NUMERIC_VALUE_REFUSAL)).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('applies the null tests straight from the menu, and cancelling a value applies nothing', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: equals…');
    await user.click(screen.getByRole('button', {name: 'Cancel'}));
    await waitFor(() => expect(screen.queryByLabelText('Value')).not.toBeInTheDocument());
    expect(runQuery).toHaveBeenCalledTimes(1);

    await chooseFromMenu(user, 'note', 'Filter: is not null');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(`WHERE "note" IS NOT NULL`);
  });

  it('gives every column’s menu its own name, and says what that column is doing', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    // Two columns' menus are otherwise indistinguishable to anything that queries by name
    // — which is every test and every screen reader (AC6).
    expect(screen.getByRole('button', {name: 'Column options: id'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Column options: note'})).toBeInTheDocument();

    await chooseFromMenu(user, 'note', 'Filter: is null');
    await waitFor(() =>
      expect(screen.getByRole('button', {name: 'Column options: note, filtered'})).toBeInTheDocument()
    );
  });

  it('offers all six comparisons, and each one composes its own operator', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await user.click(screen.getByRole('button', {name: 'Column options: note'}));
    // The menu's list is derived from `FILTER_OPERATORS`, not re-written: a hand-written
    // array cast to `FilterOperator[]` type-checks with three of the six missing, and
    // nothing here exercised more than two of them.
    const labels = screen.getAllByRole('menuitem').map((item) => item.textContent);
    expect(labels).toEqual([
      'Sort ascending',
      'Sort descending',
      'Clear sort',
      'Filter: equals…',
      'Filter: does not equal…',
      'Filter: greater than…',
      'Filter: greater than or equal to…',
      'Filter: less than…',
      'Filter: less than or equal to…',
      'Filter: is null',
      'Filter: is not null',
      'Clear filter'
    ]);

    await user.click(screen.getByRole('menuitem', {name: 'Filter: does not equal…'}));
    await user.type(screen.getByLabelText('Value'), 'third');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(`WHERE "note" <> 'third'`);
  });

  it('leaves the open menu axe-clean', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await user.click(screen.getByRole('button', {name: 'Column options: note'}));
    await screen.findByRole('menu');

    await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);
  });
});

// ─── FR-002: filter by this cell's value ─────────────────────────────────────

describe('filter by this cell’s value', () => {
  it('uses the cell’s RAW value', async () => {
    const {user} = render();
    const cells = await screen.findAllByRole('gridcell');
    await user.click(cells[1]); // row 1, `note` — O'Brien

    await user.click(screen.getByRole('button', {name: 'Filter by this value'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(`WHERE "note" = 'O''Brien'`);
  });

  it('turns a NULL cell into IS NULL, never into = ‘’', async () => {
    const {user} = render();
    const cells = await screen.findAllByRole('gridcell');
    await user.click(cells[4]); // row 2, `note` — SQL NULL, drawn as the word NULL

    await user.click(screen.getByRole('button', {name: 'Filter by this value'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    // The cell READS "NULL"; filtering on what it reads would be `= 'NULL'`, which is a
    // string nobody has. Athena returns every value as a string, so this is the app's
    // distinction to make.
    expect(lastSql()).toContain(`WHERE "note" IS NULL`);
    expect(lastSql()).not.toContain(`'NULL'`);
  });

  it('replaces the filter already on that column rather than accumulating a second one', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: is null');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    await user.click(screen.getAllByRole('gridcell')[1]);
    await user.click(screen.getByRole('button', {name: 'Filter by this value'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(3));

    const sql = lastSql();
    expect(sql).toContain(`WHERE "note" = 'O''Brien'`);
    // Two filters on one column would be `IS NULL AND = 'O''Brien'` — a contradiction that
    // returns nothing, from a gesture that reads like a correction.
    expect(sql).not.toContain('IS NULL');
    expect(sql.match(/"note"/g)).toHaveLength(1);
  });

  it('refuses, with a reason, where the value could not be a predicate', async () => {
    // A numeric column whose cell holds something the renderer would emit bare and Athena
    // would reject. The refusal is `Button.disabledReason` — reachable, not hover-only.
    vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: [['1', 'x', 'Infinity']]}) as never);
    const {user} = render();
    const cells = await screen.findAllByRole('gridcell');
    await user.click(cells[2]); // row 1, `total amount`

    const control = screen.getByRole('button', {name: 'Filter by this value'});
    await waitFor(() => expect(control).toHaveAttribute('title', UNFILTERABLE_VALUE));
    await user.click(control);
    expect(runQuery).toHaveBeenCalledTimes(1);
  });
});

// ─── The grid keeps working around the menu ──────────────────────────────────

describe('the header menu inside the grid', () => {
  it('does not select the column when the menu is used', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await user.click(screen.getByRole('button', {name: 'Column options: note'}));
    // Clicking the header itself selects the whole column (SPEC-180 FR-002 AC3); clicking
    // the menu inside it must not, or every filter gesture would select 100 cells first.
    expect(within(screen.getByRole('grid')).queryAllByRole('gridcell', {selected: true})).toHaveLength(0);
  });
});
