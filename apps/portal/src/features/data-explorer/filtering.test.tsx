import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {chooseExplorationOption} from './explorationOptions.testkit';
import {authenticated} from '../../test/authFixtures';
import {politeAnnouncements} from '../../test/liveRegions';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {NUMERIC_VALUE_REFUSAL, VALUES_FIELD_LABEL} from './FilterValueDialog';
import {EMPTY_TEXT_REFUSAL, NO_VALUES_REFUSAL, numericLineRefusal} from './explorationQueryOps';
import {NO_HISTORY_BACK} from './FilterHistoryControls';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {ALSO_IN_THE_LIST} from './FilterValuesField';
import type {ColumnFilter, ExplorationTabsState} from './dataExplorer.types';

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
  const {container} = renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
  return {user, container};
}

function seedTab(filters: ColumnFilter[] = []) {
  const created = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  const exploration = {...created, query: {...created.query, filters}};
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

  // The grid scrolls in a box bounded to the viewport, and a menu positioned inside it was
  // clipped: rightward past the last column, and downward past the box on a laptop screen.
  // jsdom lays nothing out, so the box and the button are given the sizes a 1366×650 window has.
  it('opens a header menu inside the grid box: leftward at the right edge, no taller than the room below', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const trigger = screen.getByRole('button', {name: 'Column options: note'});
    const box = trigger.closest('[data-grid-scroll-box]') as HTMLElement;
    box.getBoundingClientRect = () => new DOMRect(0, 200, 800, 340);
    Object.defineProperty(box, 'clientWidth', {configurable: true, value: 798});
    Object.defineProperty(box, 'clientHeight', {configurable: true, value: 329});
    trigger.getBoundingClientRect = () => new DOMRect(700, 205, 24, 24);

    await user.click(trigger);

    const menu = screen.getByRole('menu');
    expect(menu).toHaveClass('right-0');
    // 200 + 329 is the box's content bottom, 229 the button's, less the 8px kept clear.
    expect(menu).toHaveStyle({maxHeight: '292px'});
  });

  it('offers every operator a text column takes, and each one composes its own', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await user.click(screen.getByRole('button', {name: 'Column options: note'}));
    // The menu's list is derived from the operator table, not re-written: a hand-written
    // array cast to `FilterOperator[]` type-checks with half of them missing, and nothing
    // here exercised more than two. The ORDER is asserted because it is the offer order,
    // and an operator that needs something typed keeps the trailing ellipsis.
    const labels = screen.getAllByRole('menuitem').map((item) => item.textContent);
    expect(labels).toEqual([
      'Sort ascending',
      'Sort descending',
      'Clear sort',
      'Filter by value…',
      'Filter: equals…',
      'Filter: does not equal…',
      'Filter: greater than…',
      'Filter: greater than or equal to…',
      'Filter: less than…',
      'Filter: less than or equal to…',
      'Filter: contains…',
      'Filter: does not contain…',
      'Filter: starts with…',
      'Filter: ends with…',
      'Filter: is like…',
      'Filter: is not like…',
      'Filter: is one of…',
      'Filter: is not one of…',
      'Filter: is null',
      'Filter: is not null',
      'Filter: is empty',
      'Filter: is not empty',
      'Clear filter',
      'Hide column'
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

// ─── SPEC-238 FR-004: which operators a column offers, and the two value inputs ──────────

/** Every filter item the column's menu offers, in the order it offers them. */
async function filterItemsOf(user: ReturnType<typeof userEvent.setup>, column: string): Promise<string[]> {
  await user.click(await screen.findByRole('button', {name: new RegExp(`^Column options: ${column}`)}));
  return screen
    .getAllByRole('menuitem')
    .map((item) => item.textContent ?? '')
    .filter((label) => label.startsWith('Filter:') || label === 'Clear filter');
}

describe('the operators a column offers, by its type', () => {
  it('offers a number column the list tests but no text or empty one', async () => {
    // A `bigint` column, because `LIKE` and `= ''` against one are Trino TYPE ERRORS
    // rather than comparisons — offering them would take the exploration to an error banner.
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({columns: [{name: 'qty', type: 'bigint'}], rows: [['1']]}) as never
    );
    const {user} = render();
    await screen.findAllByRole('gridcell');

    // The whole list, not the absence of a named few: a text operator added later with the wrong
    // `offeredOn` would pass a check that never names it.
    expect(await filterItemsOf(user, 'qty')).toEqual([
      'Filter: equals…',
      'Filter: does not equal…',
      'Filter: greater than…',
      'Filter: greater than or equal to…',
      'Filter: less than…',
      'Filter: less than or equal to…',
      'Filter: is one of…',
      'Filter: is not one of…',
      'Filter: is null',
      'Filter: is not null',
      'Clear filter'
    ]);
  });

  it('offers a date column the comparisons and the null tests only', async () => {
    // `IN ('2026-01-01')` against a `date` is the same type error, since the model quotes
    // every non-numeric value.
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({columns: [{name: 'day', type: 'date'}], rows: [['2026-01-01']]}) as never
    );
    const {user} = render();
    await screen.findAllByRole('gridcell');

    expect(await filterItemsOf(user, 'day')).toEqual([
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
  });
});

describe('the text and empty operators from the menu', () => {
  it('folds case on both sides and names the escape character', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: contains…');
    await user.type(screen.getByLabelText('Value'), 'abc');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(`lower("note") LIKE lower('%abc%') ESCAPE '\\'`);
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('refuses an empty pattern, which would match every non-NULL row', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: starts with…');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    expect(await screen.findByText(EMPTY_TEXT_REFUSAL)).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('applies is empty straight from the menu, without opening a dialog', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: is empty');

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(lastSql()).toContain(`WHERE ("note" IS NULL OR "note" = '')`);
  });
});

describe('the list operators from the menu', () => {
  it('ignores blank lines, collapses duplicates, and keeps the first of each', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: is one of…');
    await user.type(screen.getByLabelText(VALUES_FIELD_LABEL), 'NY\n\nNJ\nNY');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    // Rendered sorted — two lists holding the same values are one statement and one bill.
    expect(lastSql()).toContain(`WHERE "note" IN ('NJ', 'NY')`);
  });

  it('pre-fills an edit in the STORED order, and re-applying it unchanged runs nothing new', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: is one of…');
    await user.type(screen.getByLabelText(VALUES_FIELD_LABEL), 'NY\nNJ');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    await chooseFromMenu(user, 'note', 'Filter: is one of…');
    // The lines the user typed, not the order the renderer sorts them into.
    expect(await screen.findByLabelText(VALUES_FIELD_LABEL)).toHaveValue('NY\nNJ');

    await user.click(screen.getByRole('button', {name: 'Apply filter'}));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    // Same query, so no second execution and no history entry to step back through: Back
    // reaches the UNFILTERED statement, which it could not if the re-apply had pushed one.
    expect(runQuery).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', {name: 'Back to the previous version of this query'}));
    await waitFor(() =>
      expect(screen.getByRole('button', {name: 'Back to the previous version of this query'})).toHaveAttribute(
        'title',
        NO_HISTORY_BACK
      )
    );
  });

  it('opens with the list field focused, and Enter in it is a new line rather than a submit', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: is one of…');
    const field = await screen.findByLabelText(VALUES_FIELD_LABEL);
    // `FormDialog` focuses its first control when no ref is passed, and that ref doubles as
    // the one field Enter submits from — which a list of values must not be.
    expect(field).toHaveFocus();

    await user.type(field, 'NY{Enter}NJ');
    expect(field).toHaveValue('NY\nNJ');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('has no accessibility violations in list mode, refusal included', async () => {
    const {user, container} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: is one of…');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));
    // Asserted with the refusal RENDERED: the message is wired by `aria-describedby` and
    // `aria-invalid`, and an empty field is the state that has neither.
    expect(await screen.findByText(NO_VALUES_REFUSAL)).toBeInTheDocument();
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('adds NULL to an applied list with its box, and that alone is a new statement', async () => {
    seedTab([{column: 'note', operator: 'in', values: ['a'], valueKind: 'string'}]);
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await chooseFromMenu(user, 'note', 'Filter: is one of…');

    await user.click(
      within(screen.getByRole('group', {name: `${ALSO_IN_THE_LIST} note`})).getByRole('checkbox', {name: 'NULL'})
    );
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(`WHERE ("note" IN ('a') OR "note" IS NULL)`);
    const stored = JSON.parse(sessionStorage.getItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`) ?? '{}');
    expect(stored.tabs[0].history.past).toHaveLength(1);
  });

  it('takes NULL back out of an applied list, and that is a new statement too', async () => {
    seedTab([{column: 'note', operator: 'in', values: ['a'], includesNull: true, valueKind: 'string'}]);
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await chooseFromMenu(user, 'note', 'Filter: is one of…');

    await user.click(screen.getByRole('checkbox', {name: 'NULL'}));
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql().endsWith(`WHERE "note" IN ('a')`)).toBe(true);
  });

  it('writes a line, (empty) and NULL as one list', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await chooseFromMenu(user, 'note', 'Filter: is one of…');

    await user.type(screen.getByLabelText(VALUES_FIELD_LABEL), 'a');
    await user.click(screen.getByRole('checkbox', {name: '(empty)'}));
    await user.click(screen.getByRole('checkbox', {name: 'NULL'}));
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(`WHERE ("note" IN ('', 'a') OR "note" IS NULL)`);
  });

  it.each([
    ['a text column’s is not one of', 'note', 'Filter: is not one of…', {empty: true, nul: false}],
    ['a number column’s is one of', 'total amount', 'Filter: is one of…', {empty: false, nul: true}]
  ])('offers %s only the boxes it can use', async (_case, column, item, offered) => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, column, item);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryAllByRole('checkbox', {name: '(empty)'})).toHaveLength(offered.empty ? 1 : 0);
    expect(within(dialog).queryAllByRole('checkbox', {name: 'NULL'})).toHaveLength(offered.nul ? 1 : 0);
  });

  it('names the line a number column cannot read, counting blank lines', async () => {
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({columns: [{name: 'qty', type: 'bigint'}], rows: [['1']]}) as never
    );
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'qty', 'Filter: is one of…');
    await user.type(screen.getByLabelText(VALUES_FIELD_LABEL), '1\nx\n3');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));

    expect(await screen.findByText(numericLineRefusal(2))).toBeInTheDocument();
    // Raised by Apply, with focus on the button: spoken, or a screen reader hears nothing.
    expect(politeAnnouncements()).toContainEqual(expect.stringContaining(numericLineRefusal(2)));
    expect(runQuery).toHaveBeenCalledTimes(1);
  });
});

describe('Order and filter refuses what the value dialog refuses', () => {
  const openOrderFilter = async (user: ReturnType<typeof userEvent.setup>) => {
    await chooseExplorationOption(user, 'Order and filter');
    return screen.findByRole('dialog', {name: 'Order and filter'});
  };

  it('refuses an empty text operator on that column’s row, and starts nothing', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const dialog = await openOrderFilter(user);
    await user.selectOptions(within(dialog).getByLabelText('Filter note'), 'contains');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    expect(await screen.findByText(EMPTY_TEXT_REFUSAL)).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('pre-fills a list that is ALREADY applied, so Apply does not refuse a column nobody touched', async () => {
    // The dialog unmounts on Cancel, so an empty start showed a blank field for a list that
    // was still applied — and then refused Apply for a column the user had not been near,
    // with the list only reappearing if they cycled the operator dropdown.
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Filter: is one of…');
    await user.type(screen.getByLabelText(VALUES_FIELD_LABEL), 'NY\nNJ');
    await user.click(screen.getByRole('button', {name: 'Apply filter'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    const dialog = await openOrderFilter(user);
    expect(within(dialog).getByLabelText('Values for note, one per line')).toHaveValue('NY\nNJ');

    // Apply without touching the list: the dialog closes, and the statement is unchanged —
    // so the staged list reached the query rather than being parsed from an empty field.
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));
    await waitFor(() => expect(screen.queryByRole('dialog', {name: 'Order and filter'})).not.toBeInTheDocument());
    expect(runQuery).toHaveBeenCalledTimes(2);
    expect(lastSql()).toContain(`"note" IN ('NJ', 'NY')`);
  });

  it('keeps a list holding (empty) and NULL through an Apply that touched nothing', async () => {
    seedTab([{column: 'note', operator: 'in', values: ['a', ''], includesNull: true, valueKind: 'string'}]);
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await openOrderFilter(user);
    expect(within(dialog).getByLabelText('Values for note, one per line')).toHaveValue('a');
    expect(within(dialog).getByRole('checkbox', {name: '(empty)'})).toBeChecked();
    expect(within(dialog).getByRole('checkbox', {name: 'NULL'})).toBeChecked();

    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(screen.queryByRole('dialog', {name: 'Order and filter'})).not.toBeInTheDocument());
    expect(runQuery).toHaveBeenCalledTimes(1);
    expect(lastSql()).toContain(`("note" IN ('', 'a') OR "note" IS NULL)`);
  });

  it('applies a list on one column and a pattern on another as ONE execution', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const dialog = await openOrderFilter(user);
    await user.selectOptions(within(dialog).getByLabelText('Filter note'), 'in');
    await user.type(within(dialog).getByLabelText('Values for note, one per line'), 'NY\nNJ');
    await user.selectOptions(within(dialog).getByLabelText('Filter id'), 'contains');
    await user.type(within(dialog).getByLabelText('Value for id'), 'a');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    // The whole point of the staged dialog: several changes are one execution, not one each.
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    const sql = lastSql();
    expect(sql).toContain(`"note" IN ('NJ', 'NY')`);
    expect(sql).toContain(`lower("id") LIKE lower('%a%') ESCAPE '\\'`);
  });
});
