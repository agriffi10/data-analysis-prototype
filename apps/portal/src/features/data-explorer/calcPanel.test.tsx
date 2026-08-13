import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {CALC_NO_SELECTION} from './CalcPanel';
import {calcScopeText} from './calc';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState} from './dataExplorer.types';

// SPEC-182 FR-001 and FR-002: the Calc panel. The claim that matters most here is a
// NEGATIVE one — every gesture in this file leaves `runQuery` on the single execution the
// tab opened with. Calc aggregates the selection, and a selection is client state.

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
  {name: 'note', type: 'varchar'},
  {name: 'qty', type: 'double'}
];
// A NULL, an empty string and a non-numeric value, so the three distinctions the panel has
// to keep are all present in one page.
const ROWS: (string | null)[][] = [
  ['1', 'a', '10'],
  ['2', null, '20'],
  ['3', '', 'lots']
];

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

/** Opens the panel and returns it, so every query below is scoped to the panel. */
async function openCalc(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', {name: 'Calc'}));
  return screen.getByRole('complementary', {name: 'Calc'});
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

/** Extends the selection to a cell, exactly as a Shift+click does. */
async function shiftClick(user: ReturnType<typeof userEvent.setup>, target: HTMLElement) {
  await user.keyboard('{Shift>}');
  await user.click(target);
  await user.keyboard('{/Shift}');
}

/**
 * The value shown against one function.
 *
 * Read out of the `<dt>` rather than by text: every function's name appears TWICE in the
 * panel — once as a result and once as the checkbox that adds it — so a plain text query
 * matches the control instead of the answer.
 */
function valueOf(panel: HTMLElement, label: string): string {
  const term = within(panel)
    .getAllByRole('term')
    .find((dt) => dt.textContent === label);
  return term?.parentElement?.querySelector('dd')?.textContent ?? '';
}

/** The functions the panel is currently showing an answer for, in display order. */
function shownFunctions(panel: HTMLElement): string[] {
  return within(panel)
    .queryAllByRole('term')
    .map((dt) => dt.textContent ?? '');
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);
  vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: 'exec-1'}) as never);
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({
      queryExecutionId: 'exec-1',
      state: 'SUCCEEDED',
      dataScannedBytes: 2048,
      engineExecutionTimeMillis: 120
    }) as never
  );
  vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: ROWS}) as never);
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the Calc panel', () => {
  it('never shows a Count of 0 beside a non-empty selection', async () => {
    // The two numbers this panel must never print together. Text cells are ordinary, and
    // "3 selected cells" over "Count 0" reads as a broken panel rather than as a mode.
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'note'});
    await user.click(cell(0, 'note'));
    const panel = await openCalc(user);
    await shiftClick(user, cell(2, 'note'));

    await waitFor(() => expect(within(panel).getByText(calcScopeText(3))).toBeInTheDocument());
    expect(valueOf(panel, 'Count')).toContain('2'); // 'a', '', and one NULL
    expect(valueOf(panel, 'Count')).not.toContain('0 ');
  });

  it('shows Count and Count distinct over the selection, and recomputes as it changes', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});
    await user.click(cell(0, 'id'));
    const panel = await openCalc(user);

    expect(within(panel).getByText(calcScopeText(1))).toBeInTheDocument();
    expect(valueOf(panel, 'Count')).toContain('1');
    expect(shownFunctions(panel)).toEqual(['Count', 'Count distinct']);

    // Extending down the `id` column: three cells, three distinct values.
    await shiftClick(user, cell(2, 'id'));
    await waitFor(() => expect(within(panel).getByText(calcScopeText(3))).toBeInTheDocument());
    expect(valueOf(panel, 'Count')).toContain('3');
    expect(valueOf(panel, 'Count distinct')).toContain('3');
  });

  it('recomputes over a discontiguous selection', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});
    await user.click(cell(0, 'id'));
    const panel = await openCalc(user);

    // A Ctrl/Cmd+click appends a separate single-cell rectangle — the case a model that
    // only tracked one rectangle would silently drop.
    await user.keyboard('{Meta>}');
    await user.click(cell(2, 'id'));
    await user.keyboard('{/Meta}');
    await waitFor(() => expect(within(panel).getByText(calcScopeText(2))).toBeInTheDocument());
    expect(valueOf(panel, 'Count')).toContain('2');
  });

  it('explains itself with nothing selected rather than showing zeroes', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const panel = await openCalc(user);

    // Zeroes would read as a computed answer to a question nobody asked (FR-002 AC2).
    expect(within(panel).getByText(CALC_NO_SELECTION)).toBeInTheDocument();
    expect(shownFunctions(panel)).toEqual([]);
  });

  it('says the selection is on this page, and never that it is the table', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});
    await user.click(cell(0, 'id'));
    const panel = await openCalc(user);

    // The panel's whole honesty requirement is this sentence: its numbers describe
    // selected, loaded cells and must never read as a whole-table figure.
    expect(within(panel).getByText(/on this page/)).toBeInTheDocument();
    expect(within(panel).queryByText(/all rows|whole table|total rows/i)).not.toBeInTheDocument();
  });

  it('counts NULL and not the empty string', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'note'});
    await user.click(cell(0, 'note'));
    const panel = await openCalc(user);
    await user.click(within(panel).getByRole('checkbox', {name: 'Count nulls'}));

    // Down the `note` column: 'a', NULL, ''. One null — the empty string is a value.
    await shiftClick(user, cell(2, 'note'));
    await waitFor(() => expect(within(panel).getByText(calcScopeText(3))).toBeInTheDocument());
    expect(valueOf(panel, 'Count nulls')).toContain('1');
  });

  it('skips non-numeric cells for a sum and reports how many', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'qty'});
    await user.click(cell(0, 'qty'));
    const panel = await openCalc(user);
    await user.click(within(panel).getByRole('checkbox', {name: 'Sum'}));

    await shiftClick(user, cell(2, 'qty')); // 10, 20, 'lots'
    await waitFor(() => expect(within(panel).getByText(calcScopeText(3))).toBeInTheDocument());
    const sum = valueOf(panel, 'Sum');
    expect(sum).toContain('30');
    expect(sum).toContain('1 skipped');
    expect(sum).not.toContain('NaN');
  });

  it('switches between numeric-only and mixed aggregation', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'qty'});
    await user.click(cell(0, 'qty'));
    const panel = await openCalc(user);
    await shiftClick(user, cell(2, 'qty')); // 10, 20, 'lots'
    await waitFor(() => expect(within(panel).getByText(calcScopeText(3))).toBeInTheDocument());

    // The panel OPENS mixed, so Count answers the question the selection asked: three
    // cells were selected, three cells were counted. A numbers-only default would print
    // `Count 0` directly under "3 selected cells on this page".
    expect(valueOf(panel, 'Count')).toContain('3');
    await user.click(within(panel).getByRole('checkbox', {name: 'Include text values'}));
    await waitFor(() => expect(valueOf(panel, 'Count')).toContain('2'));
  });

  it('adds, removes and resets functions', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'qty'});
    await user.click(cell(0, 'qty'));
    const panel = await openCalc(user);

    await user.click(within(panel).getByRole('checkbox', {name: 'Maximum'}));
    await waitFor(() => expect(valueOf(panel, 'Maximum')).toContain('10'));
    // Added in the panel's own order rather than the order the boxes were ticked — a list
    // that reshuffles as functions come and go is a list nobody can scan.
    expect(shownFunctions(panel)).toEqual(['Count', 'Count distinct', 'Maximum']);

    await user.click(within(panel).getByRole('checkbox', {name: 'Count distinct'}));
    await waitFor(() => expect(shownFunctions(panel)).toEqual(['Count', 'Maximum']));

    await user.click(within(panel).getByRole('button', {name: 'Reset functions'}));
    await waitFor(() => expect(shownFunctions(panel)).toEqual(['Count', 'Count distinct']));
  });

  it('issues ZERO executions for every Calc interaction', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'qty'});
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1)); // the tab's own execution

    const panel = await openCalc(user);
    await user.click(cell(0, 'id'));
    await shiftClick(user, cell(2, 'qty'));
    await user.click(within(panel).getByRole('checkbox', {name: 'Median'}));
    await user.click(within(panel).getByRole('checkbox', {name: 'Include text values'}));
    await user.click(within(panel).getByRole('button', {name: 'Reset functions'}));
    await user.click(within(panel).getByRole('button', {name: 'Close calc panel'}));

    // Asserted by count, per FR-001 AC7. Aggregating the selection server-side would be a
    // billed query per selection change.
    expect(runQuery).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('complementary', {name: 'Calc'})).not.toBeInTheDocument();
  });

  it('leaves the open panel axe-clean', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});
    await user.click(cell(0, 'id'));
    await openCalc(user);

    await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);
  });
});
