import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {CLEAR_ALL_LABEL, CLEAR_ALL_WITH_GROUPING_LABEL} from './useExplorationQuery';
import {GeneratedSqlDisclosure, NO_GENERATED_SQL} from './GeneratedSqlDisclosure';
import {CALCULATED_COLUMN_REFUSAL} from './ExplorationResultsRegion';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState} from './dataExplorer.types';
import {chooseExplorationOption, explorationOption} from './explorationOptions.testkit';

// SPEC-182 FR-003 to FR-006: the Grouping panel and the generated-SQL disclosure. Grouping
// is the Calc panel's opposite — it renders SQL and mints an execution — so every claim
// here is about the STATEMENT that reaches Athena and about how many statements do.

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
  {name: 'status', type: 'varchar'},
  {name: 'qty', type: 'double'}
];
const ROWS: (string | null)[][] = [
  ['1', 'open', '10'],
  ['2', 'paid', '20'],
  ['3', 'open', '30']
];
// What a grouped statement comes back as: the grouping columns, then the aggregates.
const GROUPED_COLUMNS = [
  {name: 'status', type: 'varchar'},
  {name: 'count_all', type: 'bigint'}
];
const GROUPED_ROWS: (string | null)[][] = [
  ['open', '2'],
  ['paid', '6']
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

async function openGrouping(user: ReturnType<typeof userEvent.setup>) {
  await chooseExplorationOption(user, 'Grouping');
  return screen.getByRole('complementary', {name: 'Grouping'});
}

/**
 * The statement the exploration currently holds, read from the disclosure.
 *
 * Not `lastSql()`, which is the last statement RUN: when a description resolves to a
 * cached execution nothing new is started, so the last call describes a query the user has
 * moved on from. Open the disclosure first.
 */
function shownSql(): string {
  return (screen.getByLabelText('Generated SQL') as HTMLTextAreaElement).value;
}

/** The cell at (row, column) — rows are the grid's body rows, 0-based. */
function cell(row: number, name: string): HTMLElement {
  const columns = screen
    .getAllByRole('columnheader')
    .map((th) => th.getAttribute('aria-label'))
    .filter((label): label is string => label !== null && label !== '#');
  const bodyRow = screen.getAllByRole('row')[row + 1]; // row 0 is the header
  return within(bodyRow).getAllByRole('gridcell')[columns.indexOf(name)];
}

/** Stages one grouping column through the explicit control. */
async function addColumn(user: ReturnType<typeof userEvent.setup>, panel: HTMLElement, name: string) {
  await user.selectOptions(within(panel).getByRole('combobox', {name: 'Column to group by'}), name);
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  sqlByExecution.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(
    ok({name: 'alice', tables: [{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: COLUMNS}]}) as never
  );
  vi.mocked(listTables).mockResolvedValue(
    ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: COLUMNS}]) as never
  );

  let seq = 0;
  vi.mocked(runQuery).mockImplementation((async ({sql}: {sql: string}) => {
    seq += 1;
    const queryExecutionId = `exec-${seq}`;
    sqlByExecution.set(queryExecutionId, sql);
    return ok({queryExecutionId});
  }) as never);
  vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
    ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})) as never);
  // A grouped statement returns the grouped shape, so "the grid shows the grouped result"
  // is observed rather than asserted about the SQL string alone.
  vi.mocked(getQueryResults).mockImplementation((async ({queryExecutionId}: {queryExecutionId: string}) => {
    const sql = sqlByExecution.get(queryExecutionId) ?? '';
    return sql.includes('GROUP BY')
      ? ok({columns: GROUPED_COLUMNS, rows: GROUPED_ROWS})
      : ok({columns: COLUMNS, rows: ROWS});
  }) as never);
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ─── FR-003: the panel renders GROUP BY ──────────────────────────────────────

describe('the Grouping panel', () => {
  it('groups by a column with COUNT(*) present by default, in ONE execution', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openGrouping(user);

    await addColumn(user, panel, 'status');
    // Several staged changes, one Apply, one execution (AC4) — the whole point of staging.
    await user.click(within(panel).getByRole('checkbox', {name: 'Show duplicates only'}));
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toBe(
      'SELECT "status", COUNT(*) AS "count_all"\n' +
        'FROM "alice"."orders"\n' +
        'GROUP BY "status"\n' +
        'HAVING COUNT(*) > 1'
    );
    // AC1 names the DISCLOSED SQL, not the statement alone.
    await user.click(screen.getByText('Generated SQL'));
    expect(shownSql()).toContain('HAVING COUNT(*) > 1');
    // The grid adopts the changed column set (AC5): the grouping columns, then the
    // aggregates, and nothing of the ungrouped result.
    await waitFor(() => expect(screen.getByRole('columnheader', {name: 'count_all'})).toBeInTheDocument());
    expect(screen.queryByRole('columnheader', {name: 'qty'})).not.toBeInTheDocument();
  });

  it('takes a column dragged from a grid header', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openGrouping(user);

    // The grip inside the header starts the drag; the panel is a drop target outside the
    // grid entirely, which is why the dragged column travels by callback and not through
    // `dataTransfer` (not implemented here, and not everywhere).
    const grip = within(screen.getByRole('columnheader', {name: 'status'})).getByTitle('status');
    fireEvent.dragStart(grip);
    fireEvent.drop(panel);

    await waitFor(() => expect(within(panel).getByRole('button', {name: 'Remove status from grouping'})).toBeDefined());
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain('GROUP BY "status"');
  });

  it('adds an aggregate against a named column and refuses a second with the same name', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openGrouping(user);
    await addColumn(user, panel, 'status');

    await user.selectOptions(within(panel).getByRole('combobox', {name: 'Aggregate function'}), 'SUM');
    await user.selectOptions(within(panel).getByRole('combobox', {name: 'Aggregate column'}), 'qty');
    await user.click(within(panel).getByRole('button', {name: 'Add'}));
    // A second SUM("qty") produces one output name twice — the renderer refuses it with a
    // message SPEC-106 forbids showing, so the panel has to turn it back first.
    await user.click(within(panel).getByRole('button', {name: 'Add'}));
    expect(within(panel).getByRole('alert')).toBeInTheDocument();

    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain('SELECT "status", COUNT(*) AS "count_all", SUM("qty") AS "sum_qty"');
    expect(lastSql().match(/SUM/g)).toHaveLength(1);
  });

  it('offers `*` for COUNT alone', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openGrouping(user);
    const column = within(panel).getByRole('combobox', {name: 'Aggregate column'});

    expect(within(column).getByRole('option', {name: 'All rows (*)'})).toBeInTheDocument();
    await user.selectOptions(within(panel).getByRole('combobox', {name: 'Aggregate function'}), 'MIN');
    // `MIN(*)` is not SQL. The renderer refuses it; the picker never offers it.
    expect(within(column).queryByRole('option', {name: 'All rows (*)'})).not.toBeInTheDocument();
  });

  it('leaves grouping mode when the last column goes, returning to the cached execution', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openGrouping(user);
    await addColumn(user, panel, 'status');
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    await user.click(within(panel).getByRole('button', {name: 'Remove status from grouping'}));
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));

    // The ungrouped statement is the one this tab opened with, so it is a CACHE HIT — the
    // execution count does not move (AC6).
    await waitFor(() => expect(screen.getByRole('columnheader', {name: 'qty'})).toBeInTheDocument());
    expect(runQuery).toHaveBeenCalledTimes(2);
  });
});

// ─── FR-004: the extras ──────────────────────────────────────────────────────

describe('grouping’s extras', () => {
  it('shows each grouped row’s share of the page, labelled as being of the page', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openGrouping(user);
    await addColumn(user, panel, 'status');
    await user.click(within(panel).getByRole('checkbox', {name: /Show percentage/}));
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));

    // 2 and 6 of 8: computed in the browser from the rows already fetched, and NOT in the
    // SQL — a windowed total would be a second scan for a column the user asked to see.
    const percentColumn = await screen.findByRole('columnheader', {name: '% of count_all (this page)'});
    expect(percentColumn).toBeInTheDocument();
    expect(lastSql()).not.toContain('OVER');
    await waitFor(() => expect(screen.getByText('25%')).toBeInTheDocument());
    expect(screen.getByText('75%')).toBeInTheDocument();
  });

  it('refuses to sort or filter the calculated percentage column, from every surface', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openGrouping(user);
    await addColumn(user, panel, 'status');
    await user.click(within(panel).getByRole('checkbox', {name: /Show percentage/}));
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));
    const percent = '% of count_all (this page)';
    await screen.findByRole('columnheader', {name: percent});
    await user.click(within(panel).getByRole('button', {name: 'Close grouping panel'}));
    expect(runQuery).toHaveBeenCalledTimes(2);

    // The column is drawn by the grid but exists in no statement: an ORDER BY on it is a
    // description the RENDERER refuses, which would take the whole exploration to an error
    // banner, and a WHERE on it is an unknown column at Athena.
    await user.click(screen.getByRole('button', {name: `Column options: ${percent}`}));
    const items = await screen.findAllByRole('menuitem');
    // Hiding is not a query edit, so the column the SQL cannot address still offers it.
    expect(items.map((item) => item.textContent)).toEqual([CALCULATED_COLUMN_REFUSAL, 'Hide column']);
    await user.keyboard('{Escape}');

    // The cursor can sit in it like any other cell, and this action does not go through
    // that menu.
    await user.click(cell(0, percent));
    const byValue = await explorationOption(user, 'Filter by this value');
    await waitFor(() => expect(byValue).toHaveAttribute('title', CALCULATED_COLUMN_REFUSAL));
    await user.click(byValue);

    // And the settings dialog, which below `tablet` is the ONLY way to sort or filter.
    await chooseExplorationOption(user, 'Order and filter');
    expect(await screen.findByRole('combobox', {name: `Sort ${percent}`})).toBeDisabled();
    expect(screen.getByRole('combobox', {name: `Filter ${percent}`})).toBeDisabled();
    // Geometry still applies to it — only the two controls that reach SQL are refused.
    expect(screen.getByRole('checkbox', {name: `Show ${percent}`})).toBeEnabled();

    expect(runQuery).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('refuses a grouping while a sort on an ungrouped column stands, and says which', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await user.click(await screen.findByRole('button', {name: /^Column options: qty/}));
    await user.click(await screen.findByRole('menuitem', {name: 'Sort ascending'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    const panel = await openGrouping(user);
    await addColumn(user, panel, 'status');

    // Trino rejects this at analysis, so nothing is scanned — what refusing here buys is
    // immediacy, and the reason has to be reachable rather than hover-only (AC3).
    const apply = within(panel).getByRole('button', {name: 'Apply grouping'});
    await waitFor(() => expect(apply).toHaveAttribute('aria-disabled', 'true'));
    expect(apply.getAttribute('title')).toContain('qty');
    await user.click(apply);

    // Not "no execution ran" — without the refusal none would run EITHER, because the
    // description would be refused by the renderer instead. What must not happen is the
    // exploration going to an error banner over a gesture the user was allowed to make.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', {name: 'qty'})).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(2);
  });
});

// ─── FR-005 and FR-006: the disclosure, and composing with the rest ──────────

describe('the generated SQL, and what grouping composes with', () => {
  it('discloses the string the execution used, grouped or not', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await user.click(screen.getByText('Generated SQL'));
    const shown = () => (screen.getByLabelText('Generated SQL') as HTMLTextAreaElement).value;
    // Available whether or not grouping is active (AC4), and byte-identical to what was
    // handed to StartQueryExecution — never a second rendering made for display.
    expect(shown()).toBe(lastSql());
    expect(screen.queryByText(NO_GENERATED_SQL)).not.toBeInTheDocument();

    const panel = await openGrouping(user);
    await addColumn(user, panel, 'status');
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));

    await waitFor(() => expect(shown()).toContain('GROUP BY "status"'));
    expect(shown()).toBe(lastSql());
  });

  it('shows the string it was GIVEN, not one it rendered', async () => {
    // FR-005 AC2 is structural — the disclosure takes a `sql` prop and has no renderer to
    // call — but "equals what ran" is satisfied by a component that re-derives, so this
    // hands it a statement no renderer would ever produce and checks it comes back whole.
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await user.click(screen.getByText('Generated SQL'));

    const textarea = screen.getByLabelText('Generated SQL') as HTMLTextAreaElement;
    expect(textarea.value).toBe(lastSql());
    expect(textarea).toHaveAttribute('readonly'); // selectable and copyable, not editable (AC3)
    expect(textarea).not.toBeDisabled(); // a disabled textarea cannot be selected from

    // The assertion above holds for a component that re-derived the SQL too, so the claim
    // is settled here: given a string no renderer could ever produce, it shows THAT.
    cleanup();
    renderWithProviders(<GeneratedSqlDisclosure sql="-- not SQL at all --" />, {auth: authenticated('alice')});
    await user.click(screen.getByText('Generated SQL'));
    expect((screen.getByLabelText('Generated SQL') as HTMLTextAreaElement).value).toBe('-- not SQL at all --');
  });

  it('clears the grouping with Clear all, and says so on the control', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await user.click(screen.getByText('Generated SQL'));
    expect(await explorationOption(user, CLEAR_ALL_LABEL)).toBeInTheDocument();

    const panel = await openGrouping(user);
    await addColumn(user, panel, 'status');
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    // The label changes because the ACTION does (FR-006 AC3) — a control that said
    // "filters" while removing a grouping would be lying about the click.
    await chooseExplorationOption(user, CLEAR_ALL_WITH_GROUPING_LABEL);
    await waitFor(() => expect(screen.getByRole('columnheader', {name: 'qty'})).toBeInTheDocument());
    expect(shownSql()).not.toContain('GROUP BY');
    expect(await explorationOption(user, CLEAR_ALL_LABEL)).toBeInTheDocument();
  });

  it('records a grouping change in the tab’s history like any other change', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openGrouping(user);
    await addColumn(user, panel, 'status');
    await user.click(within(panel).getByRole('button', {name: 'Apply grouping'}));
    await waitFor(() => expect(screen.getByRole('columnheader', {name: 'count_all'})).toBeInTheDocument());

    await user.click(screen.getByRole('button', {name: 'Back to previous filters'}));
    // Back to the ungrouped description — a cached statement, so no third execution
    // (FR-006 AC4).
    await waitFor(() => expect(screen.getByRole('columnheader', {name: 'qty'})).toBeInTheDocument());
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('leaves the open panel axe-clean', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openGrouping(user);
    await addColumn(user, panel, 'status');

    await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);
  });
});
