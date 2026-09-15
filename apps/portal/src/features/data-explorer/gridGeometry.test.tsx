import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {LAST_COLUMN_REFUSAL} from './useColumnGeometry';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {COLUMN_RESIZE_STEP_PX, DEFAULT_COLUMN_WIDTH, MIN_COLUMN_WIDTH} from '../catalog/catalog.constants';
import type {ExplorationTab, ExplorationTabsState} from './dataExplorer.types';
import {chooseExplorationOption} from './explorationOptions.testkit';

// SPEC-180 Phase 1: column geometry over the REAL workspace, the real tab state and
// SPEC-178's real engine — only the AWS boundary is mocked (react.md §21), because that
// boundary is the one place a bill would appear and FR-001 AC6 is a claim about bills.

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
    ['2', '12.50', 'open']
  ],
  nextToken: 'page-2'
};
const PAGE_TWO = {columns: COLUMNS, rows: [['3', '4.00', 'void']]};

function render(route = '/explore') {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  renderWithProviders(<DataExplorerWorkspace />, {route, auth: authenticated('alice')});
  return {user};
}

function seedTabs(tables: {id: string; table: string}[], activeTabId = tables[0]?.id ?? '') {
  const state: ExplorationTabsState = {
    version: 1,
    tabs: tables.map(({id, table}): ExplorationTab => ({
      id,
      label: table,
      exploration: newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table}, id),
      scannedByExecution: {},
      history: {past: [], future: []}
    })),
    activeTabId
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

/** The visible data columns, in display order. */
function headerNames(): string[] {
  return screen
    .getAllByRole('columnheader')
    .map((th) => th.getAttribute('aria-label') ?? th.textContent ?? '')
    .filter((name) => name !== '#');
}

/** Opens the Columns panel and returns the row for one column. */
async function columnRow(user: ReturnType<typeof userEvent.setup>, name: string) {
  if (!screen.queryByRole('dialog', {name: 'Columns'})) {
    await chooseExplorationOption(user, 'Columns');
  }
  const panel = await screen.findByRole('dialog', {name: 'Columns'});
  const row = within(panel)
    .getAllByRole('listitem')
    .find((li) => within(li).queryByRole('button', {name: new RegExp(`(Hide|Show) ${name}$`)}));
  if (!row) throw new Error(`no Columns row for ${name}`);
  return row;
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);
  let started = 0;
  vi.mocked(runQuery).mockImplementation(async () => {
    started += 1;
    return ok({queryExecutionId: `exec-${started}`});
  });
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})
  );
  vi.mocked(getQueryResults).mockImplementation(
    async ({nextToken}: {nextToken?: string}) => ok(nextToken ? PAGE_TWO : PAGE_ONE) as never
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ─── FR-001: geometry is presentation, and presentation costs nothing ────────

describe('column geometry', () => {
  it('resizes a column by keyboard, clamped at the minimum', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    render();
    const handle = await screen.findByRole('separator', {name: 'Resize column id'});

    fireEvent.keyDown(handle, {key: 'ArrowRight'});
    expect(handle).toHaveAttribute('aria-valuenow', String(DEFAULT_COLUMN_WIDTH + COLUMN_RESIZE_STEP_PX));

    // Far past the floor in one gesture — the clamp is the geometry's, not the handle's.
    fireEvent.pointerDown(handle, {clientX: 500});
    fireEvent.pointerMove(window, {clientX: 0});
    fireEvent.pointerUp(window);
    await waitFor(() => expect(handle).toHaveAttribute('aria-valuenow', String(MIN_COLUMN_WIDTH)));
  });

  // The name is the user's data and is shown as spelled; the header around it keeps the
  // caption style. Asserting the control on the SAME header is what makes this able to
  // fail if the caption style is dropped rather than overridden — jsdom loads no Tailwind,
  // so the computed text-transform is not observable and the classes are all there is.
  it('shows a column name as spelled, inside a header that still uses the caption style', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    render();
    const header = await screen.findByRole('columnheader', {name: 'total'});

    expect(within(header).getByTitle('total')).toHaveClass('normal-case');
    expect(header).toHaveClass('uppercase');
  });

  it('hides a column and shows it again, from the Columns panel', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'total'});

    await user.click(within(await columnRow(user, 'total')).getByRole('button', {name: 'Hide total'}));
    await waitFor(() => expect(headerNames()).toEqual(['id', 'status']));

    await user.click(within(await columnRow(user, 'total')).getByRole('button', {name: 'Show total'}));
    await waitFor(() => expect(headerNames()).toEqual(['id', 'total', 'status']));
  });

  it('refuses to hide the LAST visible column, with the reason in the tab order', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'total'});

    await user.click(within(await columnRow(user, 'total')).getByRole('button', {name: 'Hide total'}));
    await user.click(within(await columnRow(user, 'status')).getByRole('button', {name: 'Hide status'}));
    await waitFor(() => expect(headerNames()).toEqual(['id']));

    const last = within(await columnRow(user, 'id')).getByRole('button', {name: 'Hide id'});
    // `aria-disabled`, NOT `disabled`: the control keeps its place in the tab order, so the
    // reason is reachable rather than hover-only — and it is not inside the button, where it
    // would become part of the accessible name.
    expect(last).toHaveAttribute('aria-disabled', 'true');
    expect(last).not.toBeDisabled();
    expect(last).toHaveAttribute('title', LAST_COLUMN_REFUSAL);
    expect(last).toHaveAccessibleName('Hide id');

    await user.click(last);
    expect(headerNames()).toEqual(['id']);
  });

  // Hiding lived only in the Columns panel, which testers did not find from the grid.
  it('hides a column from its own header menu, and refuses the last one there too', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'total'});

    await user.click(screen.getByRole('button', {name: 'Column options: total'}));
    await user.click(screen.getByRole('menuitem', {name: 'Hide column'}));
    await waitFor(() => expect(headerNames()).toEqual(['id', 'status']));
    await user.click(screen.getByRole('button', {name: 'Column options: status'}));
    await user.click(screen.getByRole('menuitem', {name: 'Hide column'}));
    await waitFor(() => expect(headerNames()).toEqual(['id']));
    await user.click(screen.getByRole('button', {name: 'Column options: id'}));

    expect(screen.getByRole('menuitem', {name: 'Hide column'})).toHaveAttribute('title', LAST_COLUMN_REFUSAL);
  });

  it('puts every column back as it arrived with Show all and Unpin all', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'total'});
    await user.click(within(await columnRow(user, 'total')).getByRole('button', {name: 'Hide total'}));
    await user.click(within(await columnRow(user, 'status')).getByRole('button', {name: 'Pin status'}));
    await waitFor(() => expect(headerNames()).toEqual(['status', 'id']));
    const panel = screen.getByRole('dialog', {name: 'Columns'});

    await user.click(within(panel).getByRole('button', {name: 'Show all'}));
    await user.click(within(panel).getByRole('button', {name: 'Unpin all'}));

    await waitFor(() => expect(headerNames()).toEqual(['id', 'total', 'status']));
    expect(within(panel).getByRole('button', {name: 'Show all'})).toHaveAttribute('title', 'No column is hidden.');
  });

  it('pins a column to the front of the display order and unpins it back', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'status'});

    await user.click(within(await columnRow(user, 'status')).getByRole('button', {name: 'Pin status'}));
    await waitFor(() => expect(headerNames()).toEqual(['status', 'id', 'total']));

    await user.click(within(await columnRow(user, 'status')).getByRole('button', {name: 'Unpin status'}));
    await waitFor(() => expect(headerNames()).toEqual(['id', 'total', 'status']));
  });

  it('reorders a PINNED column within the pinned block', async () => {
    // The pinned block used to be ordered by pin order ALONE, so a move inside it was a
    // silent no-op that the live region still announced.
    seedTabs([{id: 't1', table: 'orders'}]);
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'status'});

    await user.click(within(await columnRow(user, 'status')).getByRole('button', {name: 'Pin status'}));
    await user.click(within(await columnRow(user, 'id')).getByRole('button', {name: 'Pin id'}));
    await waitFor(() => expect(headerNames()).toEqual(['status', 'id', 'total']));

    await user.click(within(await columnRow(user, 'id')).getByRole('button', {name: 'Move id earlier'}));
    await waitFor(() => expect(headerNames()).toEqual(['id', 'status', 'total']));

    const panel = screen.getByRole('dialog', {name: 'Columns'});
    expect(within(panel).getByRole('status')).toHaveTextContent('id moved to position 1 of 2.');
  });

  it('reorders by dragging one header onto another, in BOTH directions', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    render();
    await screen.findByRole('columnheader', {name: 'status'});

    const drag = async (from: string, onto: string) => {
      const dragged = within(screen.getByRole('columnheader', {name: from})).getByTitle(from);
      const target = screen.getByRole('columnheader', {name: onto});
      fireEvent.dragStart(dragged);
      fireEvent.dragOver(target);
      fireEvent.drop(target);
    };

    await drag('status', 'id'); // leftward
    await waitFor(() => expect(headerNames()).toEqual(['status', 'id', 'total']));

    // Rightward was a no-op while the insert was always BEFORE the target — half of
    // drag-reorder, silently missing.
    await drag('status', 'total');
    await waitFor(() => expect(headerNames()).toEqual(['id', 'total', 'status']));
  });

  it('keeps geometry across paging and tab switches, and costs NOTHING (FR-001 AC6/AC7)', async () => {
    seedTabs(
      [
        {id: 't1', table: 'orders'},
        {id: 't2', table: 'refunds'}
      ],
      't1'
    );
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'total'});
    // Two tabs, one active: exactly one statement has been started so far.
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await user.click(within(await columnRow(user, 'total')).getByRole('button', {name: 'Hide total'}));
    await user.click(within(await columnRow(user, 'status')).getByRole('button', {name: 'Pin status'}));
    fireEvent.keyDown(screen.getByRole('separator', {name: 'Resize column id'}), {key: 'ArrowRight'});
    await user.click(screen.getByRole('button', {name: 'Close columns'}));
    await waitFor(() => expect(headerNames()).toEqual(['status', 'id']));

    // Paging: a NextToken walk over the same execution, so still no second statement.
    await user.click(screen.getByRole('button', {name: 'Next'}));
    await waitFor(() => expect(screen.getByText(/Rows 3–3/)).toBeInTheDocument());
    expect(headerNames()).toEqual(['status', 'id']);

    // Switching away and back: the other tab runs its own statement, this one's geometry
    // comes back with it.
    await user.click(screen.getByRole('tab', {name: /refunds/}));
    await screen.findByRole('columnheader', {name: 'total'});
    await user.click(screen.getByRole('tab', {name: /orders/}));
    await waitFor(() => expect(headerNames()).toEqual(['status', 'id']));
    expect(screen.getByRole('separator', {name: 'Resize column id'})).toHaveAttribute(
      'aria-valuenow',
      String(DEFAULT_COLUMN_WIDTH + COLUMN_RESIZE_STEP_PX)
    );

    // The count that matters: one statement per TAB, and not one for any gesture above.
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('does not apply the geometry of a column the result no longer has (FR-006 AC3)', async () => {
    // A hide, a pin and a width against `total`, restored over a result set that has
    // dropped it and gained `refunded` in its place. Name-keyed geometry cannot land on
    // the newcomer; position-keyed geometry would have.
    const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
    const state: ExplorationTabsState = {
      version: 1,
      tabs: [
        {
          id: 't1',
          label: 'orders',
          exploration: {
            ...exploration,
            presentation: {
              ...exploration.presentation,
              hiddenColumns: ['total'],
              pinnedColumns: ['total'],
              columnWidths: {total: 320}
            }
          },
          scannedByExecution: {},
          history: {past: [], future: []}
        }
      ],
      activeTabId: 't1'
    };
    sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({
        columns: [
          {name: 'id', type: 'varchar'},
          {name: 'refunded', type: 'double'}
        ],
        rows: [['1', '0.00']]
      }) as never
    );
    render();

    await screen.findByRole('columnheader', {name: 'refunded'});
    expect(headerNames()).toEqual(['id', 'refunded']);
    expect(screen.getByRole('separator', {name: 'Resize column refunded'})).toHaveAttribute(
      'aria-valuenow',
      String(DEFAULT_COLUMN_WIDTH)
    );
  });
});

// ─── FR-006: columns may be unknown until the first execution ────────────────

describe('columns before the first execution', () => {
  const GLUE_COLUMNS = [
    {name: 'id', type: 'string'},
    {name: 'total', type: 'double'},
    {name: 'status', type: 'string'}
  ];

  it('draws a TABLE source’s headers from Glue while the statement is still running', async () => {
    vi.mocked(listTables).mockResolvedValue(
      ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: GLUE_COLUMNS}]) as never
    );
    // The execution never settles in this test: what is on screen is what Glue knew.
    vi.mocked(getQueryResults).mockImplementation(() => new Promise(() => {}) as never);
    seedTabs([{id: 't1', table: 'orders'}]);
    render();

    await waitFor(() => expect(headerNames()).toEqual(['id', 'total', 'status']));
    // "Running…", not "Loading rows…": rows are not being fetched, and saying they are was
    // the visible face of a real defect. Results are read only at SUCCEEDED, because
    // GetQueryResults against a QUEUED execution is a 400 the app showed as
    // "Contact the Administrator" (fixed 2026-08-15). "Loading rows…" now means what it
    // says — the execution finished and its rows are on the way.
    expect(screen.getByRole('status')).toHaveTextContent('Running…');
    expect(screen.queryAllByRole('gridcell')).toHaveLength(0);
  });

  it('shows a SQL source no headers until the execution reports them', async () => {
    // No UI opens a `sql` source until SPEC-183 — the grid handles the arm now because
    // retrofitting a header path later would touch every spec in between.
    const exploration = newExploration({kind: 'sql', body: 'SELECT 1 AS n', label: 'saved.sql'}, 't1');
    const state: ExplorationTabsState = {
      version: 1,
      tabs: [{id: 't1', label: 'saved.sql', exploration, scannedByExecution: {}, history: {past: [], future: []}}],
      activeTabId: 't1'
    };
    sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
    const settle: {run: () => void} = {run: () => {}};
    vi.mocked(getQueryResults).mockImplementation(
      () =>
        new Promise((resolve) => {
          settle.run = () => resolve(ok({columns: [{name: 'n', type: 'integer'}], rows: [['1']]}) as never);
        }) as never
    );
    render();

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Loading rows…'));
    expect(screen.queryAllByRole('columnheader')).toHaveLength(0);
    expect(getDatabase).not.toHaveBeenCalled(); // a `sql` source has no database to read

    await waitFor(() => expect(getQueryResults).toHaveBeenCalled());
    settle.run();
    await waitFor(() => expect(headerNames()).toEqual(['n']));
  });

  it('adopts the EXECUTION’s columns when they disagree with the table’s (a grouping change)', async () => {
    // What a GROUP BY does: the column set is replaced wholesale, and Glue is still
    // describing the table underneath it.
    vi.mocked(listTables).mockResolvedValue(
      ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: GLUE_COLUMNS}]) as never
    );
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({
        columns: [
          {name: 'status', type: 'varchar'},
          {name: 'count_all', type: 'bigint'}
        ],
        rows: [['paid', '2']]
      }) as never
    );
    seedTabs([{id: 't1', table: 'orders'}]);
    render();

    await waitFor(() => expect(headerNames()).toEqual(['status', 'count_all']));
  });
});
