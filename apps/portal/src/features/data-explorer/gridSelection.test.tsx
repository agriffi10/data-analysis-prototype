import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTab, ExplorationTabsState} from './dataExplorer.types';

// SPEC-180 Phase 2: the cell cursor and range selection, driven through the real grid.
// A selection model is an accessibility problem a static table is not, so the axe pass
// here runs against the DRIVEN container with a live multi-cell selection — axe snapshots
// the tree when it starts, and a selection nobody made is not the state at risk.

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
  {name: 'total', type: 'double'},
  {name: 'status', type: 'varchar'}
];
const PAGE_ONE = {
  columns: COLUMNS,
  rows: [
    ['1', '9.99', 'paid'],
    ['2', '12.50', 'open'],
    ['3', '3.25', 'void']
  ],
  nextToken: 'page-2'
};
const PAGE_TWO = {columns: COLUMNS, rows: [['4', '7.00', 'paid']]};

function render() {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
  return {user};
}

function seedTab() {
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [
      {
        id: 't1',
        label: 'orders',
        exploration: newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1'),
        scannedByExecution: {}
      } satisfies ExplorationTab
    ],
    activeTabId: 't1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
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

/** Every selected cell's text, in DOM order. */
function selectedText(): string[] {
  return screen
    .getAllByRole('gridcell')
    .filter((td) => td.getAttribute('aria-selected') === 'true')
    .map((td) => td.textContent ?? '');
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
    ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})
  );
  vi.mocked(getQueryResults).mockImplementation(
    async ({nextToken}: {nextToken?: string}) => ok(nextToken ? PAGE_TWO : PAGE_ONE) as never
  );
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the cell cursor and range selection', () => {
  it('clicks a cell, extends with Shift+click and toggles a discontiguous cell with Cmd+click', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});

    await user.click(cell(0, 'id'));
    expect(selectedText()).toEqual(['1']);
    expect(screen.getByRole('status', {name: ''})).toHaveTextContent('1 cell selected on this page');

    // A rectangle, not a run of cells: two rows by two columns.
    await user.keyboard('{Shift>}');
    await user.click(cell(1, 'total'));
    await user.keyboard('{/Shift}');
    expect(selectedText()).toEqual(['1', '9.99', '2', '12.50']);

    await user.keyboard('{Meta>}');
    await user.click(cell(2, 'status'));
    await user.keyboard('{/Meta}');
    expect(selectedText()).toEqual(['1', '9.99', '2', '12.50', 'void']);

    // The same cell again removes it — a discontiguous cell TOGGLES.
    await user.keyboard('{Meta>}');
    await user.click(cell(2, 'status'));
    await user.keyboard('{/Meta}');
    expect(selectedText()).toEqual(['1', '9.99', '2', '12.50']);
  });

  it('moves the cursor with the Arrow keys and extends with Shift, keeping DOM focus on the cursor', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});

    await user.click(cell(0, 'id'));
    await user.keyboard('{ArrowRight}');
    expect(cell(0, 'total')).toHaveFocus();
    expect(selectedText()).toEqual(['9.99']);

    await user.keyboard('{Shift>}{ArrowDown}{/Shift}');
    expect(cell(1, 'total')).toHaveFocus();
    expect(selectedText()).toEqual(['9.99', '12.50']);

    // Bounded by the page: an Arrow at the edge stays put rather than wrapping.
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}');
    expect(cell(2, 'total')).toHaveFocus();
  });

  it('End and Home walk the row, PageDown and PageUp the loaded page', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});

    await user.click(cell(1, 'total'));
    await user.keyboard('{End}');
    expect(cell(1, 'status')).toHaveFocus();
    await user.keyboard('{Home}');
    expect(cell(1, 'id')).toHaveFocus();

    await user.keyboard('{PageDown}');
    expect(cell(2, 'id')).toHaveFocus();
    await user.keyboard('{PageUp}');
    expect(cell(0, 'id')).toHaveFocus();
  });

  it('selects a whole column from its header and a whole row from its number', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'total'});

    await user.click(screen.getByRole('columnheader', {name: 'total'}));
    expect(selectedText()).toEqual(['9.99', '12.50', '3.25']);

    await user.click(within(screen.getAllByRole('row')[2]).getByRole('rowheader'));
    expect(selectedText()).toEqual(['2', '12.50', 'open']);
  });

  it('Ctrl/Cmd+A selects the loaded page, and says that is what it selected', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});

    await user.click(cell(0, 'id'));
    await user.keyboard('{Meta>}a{/Meta}');

    expect(selectedText()).toHaveLength(9); // 3 rows × 3 columns — the PAGE, not the result
    expect(screen.getByRole('status', {name: ''})).toHaveTextContent('9 cells selected on this page');
  });

  it('is a single tab stop: only the cursor cell is tabbable', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});
    await user.click(cell(1, 'total'));

    const tabbable = screen.getAllByRole('gridcell').filter((td) => td.getAttribute('tabindex') === '0');
    expect(tabbable).toEqual([cell(1, 'total')]);
    expect(screen.getAllByRole('gridcell').filter((td) => td.getAttribute('tabindex') === '-1')).toHaveLength(8);
  });

  it('clears the selection on paging rather than carrying coordinates onto other rows', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});
    await user.click(cell(0, 'id'));
    await user.keyboard('{Shift>}{ArrowDown}{/Shift}');
    expect(selectedText()).toHaveLength(2);

    await user.click(screen.getByRole('button', {name: 'Next'}));
    await waitFor(() => expect(screen.getByText(/Rows 4–4/)).toBeInTheDocument());

    expect(selectedText()).toEqual([]);
  });

  it('clears the selection when the column set changes underneath it', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'total'});
    await user.click(cell(0, 'total'));
    expect(selectedText()).toEqual(['9.99']);

    // Hide a DIFFERENT column: hiding the selected one removes its cells from the DOM, so
    // "nothing is selected" would hold whether or not the reset ran — the assertion has to
    // be made where the selected cell is still on screen to be one at all.
    await user.click(screen.getByRole('button', {name: 'Columns'}));
    const panel = await screen.findByRole('dialog', {name: 'Columns'});
    await user.click(within(panel).getByRole('button', {name: 'Hide status'}));
    await user.click(screen.getByRole('button', {name: 'Close columns'}));

    await waitFor(() => expect(screen.queryByRole('columnheader', {name: 'status'})).not.toBeInTheDocument());
    expect(cell(0, 'total')).toBeInTheDocument();
    expect(selectedText()).toEqual([]);
  });

  it('moves DOM focus with the cursor on the FIRST keyboard move, with no click first', async () => {
    // The path a keyboard-only user takes: Tab into the grid, then Arrow. The cursor cell
    // is looked up in the committed DOM rather than held in a per-cell ref, because ref
    // detach/attach order is not promised and the first move read a nulled one — the
    // cursor moved and focus stayed behind.
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});

    cell(0, 'id').focus();
    await user.keyboard('{ArrowRight}');

    expect(cell(0, 'total')).toHaveFocus();
    expect(cell(0, 'total')).toHaveAttribute('tabindex', '0');
  });

  it('keeps every cell with its own column after a reorder', async () => {
    // The assertion the header-name checks cannot make: a reorder that moved the headers
    // and left the cells where they were would pass all of them.
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'status'});

    await user.click(screen.getByRole('button', {name: 'Columns'}));
    const panel = await screen.findByRole('dialog', {name: 'Columns'});
    await user.click(within(panel).getByRole('button', {name: 'Pin status'}));
    await user.click(screen.getByRole('button', {name: 'Close columns'}));

    await waitFor(() =>
      expect(
        within(screen.getAllByRole('row')[1])
          .getAllByRole('gridcell')
          .map((td) => td.textContent)
      ).toEqual(['paid', '1', '9.99'])
    );
  });

  it('Ctrl+Space selects the cursor’s column and Shift+Space its row', async () => {
    // The keyboard half of the header/row-number clicks — the WAI-ARIA grid bindings.
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'total'});

    await user.click(cell(1, 'total'));
    await user.keyboard('{Control>} {/Control}');
    expect(selectedText()).toEqual(['9.99', '12.50', '3.25']);

    // Each selector re-homes the cursor the way its pointer twin does — a column selection
    // puts it on row 1 — so the row case starts from its own click rather than from there.
    await user.click(cell(1, 'total'));
    await user.keyboard('{Shift>} {/Shift}');
    expect(selectedText()).toEqual(['2', '12.50', 'open']);
  });

  it('leaves the grid axe-clean with a multi-cell selection active', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});
    await user.click(cell(0, 'id'));
    await user.keyboard('{Shift>}{ArrowDown}{ArrowRight}{/Shift}');
    expect(selectedText()).toHaveLength(4);

    await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);
  });
});
