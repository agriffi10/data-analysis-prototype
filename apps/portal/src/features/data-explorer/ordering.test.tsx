import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {chooseExplorationOption} from './explorationOptions.testkit';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState} from './dataExplorer.types';

// SPEC-181 FR-004 and FR-005: multi-column ordering with an explicit priority, and the
// staged Order/Filter dialog whose whole point is that several changes cost ONE execution.

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
  {name: 'total', type: 'double'}
];
const ROWS = [
  ['1', 'first', '9.99'],
  ['2', 'second', '12.50']
];

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

async function chooseFromMenu(user: ReturnType<typeof userEvent.setup>, column: string, item: string) {
  await user.click(await screen.findByRole('button', {name: new RegExp(`^Column options: ${column}`)}));
  await user.click(await screen.findByRole('menuitem', {name: item}));
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
  vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: ROWS}) as never);
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ─── FR-004: multi-column ordering ───────────────────────────────────────────

describe('multi-column ordering', () => {
  it('appends a second sort at the next priority and renders them in priority order', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Sort ascending');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain('ORDER BY "note" ASC');

    await chooseFromMenu(user, 'total', 'Sort descending');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(3));
    expect(lastSql()).toContain('ORDER BY "note" ASC, "total" DESC');
  });

  it('shows each sorted column’s direction and its position', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Sort ascending');
    await chooseFromMenu(user, 'total', 'Sort descending');

    // The header cell's own `aria-label` suppresses everything inside it, so the sort has
    // to be reachable through the menu trigger's name.
    await waitFor(() =>
      expect(screen.getByRole('button', {name: 'Column options: note, sorted ascending, sort 1'})).toBeInTheDocument()
    );
    expect(screen.getByRole('button', {name: 'Column options: total, sorted descending, sort 2'})).toBeInTheDocument();
    // And visibly, beside the column name.
    expect(within(screen.getByRole('columnheader', {name: 'total'})).getByText('▼2')).toBeInTheDocument();
  });

  it('keeps the remaining priorities contiguous when one sort is cleared', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'id', 'Sort ascending');
    await chooseFromMenu(user, 'note', 'Sort ascending');
    await chooseFromMenu(user, 'total', 'Sort descending');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(4));

    await chooseFromMenu(user, 'note', 'Clear sort');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(5));
    expect(lastSql()).toContain('ORDER BY "id" ASC, "total" DESC');
    // 1 and 2, never 1 and 3 — the SQL would be the same and the user would be told there
    // is a second sort that is not there.
    await waitFor(() =>
      expect(screen.getByRole('button', {name: 'Column options: total, sorted descending, sort 2'})).toBeInTheDocument()
    );
  });

  it('flipping the direction of a sorted column keeps its place', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Sort ascending');
    await chooseFromMenu(user, 'total', 'Sort ascending');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(3));

    await chooseFromMenu(user, 'total', 'Sort descending');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(4));
    // Not promoted to primary: flipping a direction is not a request to re-order a
    // multi-column sort the user built deliberately.
    expect(lastSql()).toContain('ORDER BY "note" ASC, "total" DESC');
  });

  it('sorting and then unsorting comes back from cache, issuing NO new query', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await chooseFromMenu(user, 'note', 'Sort ascending');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    await chooseFromMenu(user, 'note', 'Clear sort');
    // Waits for the SORT to be gone from the menu's name — the cells were already on
    // screen, so waiting for them would pass on its first attempt and anchor the count
    // assertion below to nothing.
    await waitFor(() => expect(screen.getByRole('button', {name: 'Column options: note'})).toBeInTheDocument());
    // The unsorted statement is byte-identical to the one that has already run, and the
    // rendered SQL is the cache key — so this is a cache hit and not a second bill
    // (SPEC-178 FR-006).
    expect(runQuery).toHaveBeenCalledTimes(2);
  });
});

// ─── FR-005: the Order/Filter settings dialog ────────────────────────────────

describe('the Order and filter dialog', () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    await chooseExplorationOption(user, 'Order and filter');
    return screen.findByRole('dialog', {name: 'Order and filter'});
  };

  it('stages several criteria and applies them as ONE execution', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await open(user);

    // Every column appears with its own controls (AC1).
    for (const column of ['id', 'note', 'total']) {
      expect(within(dialog).getByRole('combobox', {name: `Sort ${column}`})).toBeInTheDocument();
      expect(within(dialog).getByRole('checkbox', {name: `Show ${column}`})).toBeInTheDocument();
    }

    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Sort note'}), 'asc');
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Filter total'}), '>');
    await user.type(within(dialog).getByLabelText('Value for total'), '5');
    await user.click(within(dialog).getByRole('checkbox', {name: 'Show id'}));
    // Nothing has run yet: staging is the point of the dialog.
    expect(runQuery).toHaveBeenCalledTimes(1);

    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain('WHERE "total" > 5');
    expect(lastSql()).toContain('ORDER BY "note" ASC');
    // Two criteria and a visibility change — ONE execution (AC2), and the hidden column
    // changed no SQL at all (AC4).
    expect(runQuery).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.queryByRole('columnheader', {name: 'id'})).not.toBeInTheDocument());
  });

  it('discards every staged change on Cancel, presentation included', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await open(user);

    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Sort note'}), 'desc');
    await user.click(within(dialog).getByRole('checkbox', {name: 'Show id'}));
    await user.click(within(dialog).getByRole('button', {name: 'Cancel'}));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(runQuery).toHaveBeenCalledTimes(1);
    // The presentation half is staged in the SAME object, which is what makes "Cancel
    // discards everything" structural rather than a rule two pieces of state must keep.
    expect(screen.getByRole('columnheader', {name: 'id'})).toBeInTheDocument();
  });

  it('applies a visibility change with no execution at all', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await open(user);

    await user.click(within(dialog).getByRole('checkbox', {name: 'Show note'}));
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(screen.queryByRole('columnheader', {name: 'note'})).not.toBeInTheDocument());
    // `SELECT *` always: hiding renders no SQL, so it costs nothing and applies instantly.
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('reorders sort priority inside the dialog', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await open(user);

    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Sort note'}), 'asc');
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Sort total'}), 'asc');
    // A refusal, not a disabled control: it keeps its place in the tab order and says why.
    expect(within(dialog).getByRole('button', {name: 'Sort note earlier'})).toHaveAttribute(
      'title',
      '“note” is already the first sort.'
    );
    await user.click(within(dialog).getByRole('button', {name: 'Sort total earlier'}));
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain('ORDER BY "total" ASC, "note" ASC');
  });

  it('suppresses implicit submission: Enter in a criteria row files nothing', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    const dialog = await open(user);

    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Filter note'}), '=');
    const value = within(dialog).getByLabelText('Value for note');
    await user.type(value, 'abc');

    // jsdom implements NO implicit form submission, so "the dialog did not close" would
    // pass whatever the handler does (SPEC-175's own finding). The claim is that the key
    // was intercepted — and that a `<select>` is intercepted too (SPEC-155/175).
    expect(fireEvent.keyDown(value, {key: 'Enter'})).toBe(false);
    expect(fireEvent.keyDown(within(dialog).getByRole('combobox', {name: 'Filter note'}), {key: 'Enter'})).toBe(false);
    expect(screen.getByRole('dialog', {name: 'Order and filter'})).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(1);

    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(`WHERE "note" = 'abc'`);
  });
});
