import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState} from './dataExplorer.types';
import {chooseExplorationOption} from './explorationOptions.testkit';

// The Value panel, and the table as the only presentation at every width. Every one of these is
// a view over rows that have ALREADY been fetched, so the count of `runQuery` calls is an
// assertion in its own right.

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
// Row 2 carries the pair this feature has to tell apart: a SQL NULL and an empty string.
const ROWS = [
  ['1', 'a long note that the grid truncates but the panel must not', '9.99'],
  ['2', null, ''],
  ['3', 'third', '3.25']
];

const DEFAULT_WIDTH = window.innerWidth;

function render() {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
  return {user};
}

function seedTab(presentation: Record<string, unknown> = {}) {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [
      {
        id: 't1',
        label: 'orders',
        exploration: {...exploration, presentation: {...exploration.presentation, ...presentation}},
        scannedByExecution: {},
        history: {past: [], future: []}
      }
    ],
    activeTabId: 't1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  window.innerWidth = DEFAULT_WIDTH;
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);
  vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: 'exec-1'}) as never);
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})
  );
  vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: ROWS}) as never);
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  window.innerWidth = DEFAULT_WIDTH;
});

// ─── FR-003: the Value panel ─────────────────────────────────────────────────

describe('the Value panel', () => {
  it('shows the focused cell’s COMPLETE value and follows the cursor', async () => {
    const {user} = render();
    const cells = await screen.findAllByRole('gridcell');
    await user.click(cells[1]); // row 1, `note`
    await chooseExplorationOption(user, 'Value');

    const panel = await screen.findByRole('complementary', {name: 'Value'});
    expect(within(panel).getByRole('textbox', {name: 'Value of note'})).toHaveValue(ROWS[0][1] as string);

    // It updates as the cursor moves, without a second query.
    await user.click(screen.getAllByRole('gridcell')[2]); // row 1, `total`
    expect(within(panel).getByRole('textbox', {name: 'Value of total'})).toHaveValue('9.99');
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('tells a NULL and an empty string apart', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await chooseExplorationOption(user, 'Value');
    const panel = await screen.findByRole('complementary', {name: 'Value'});

    // Athena returns every value as a string, so this distinction is the app's to make —
    // and both cells would otherwise render as an identical empty box.
    await user.click(screen.getAllByRole('gridcell')[4]); // row 2, `note` — SQL NULL
    expect(panel).toHaveTextContent('NULL');
    await user.click(screen.getAllByRole('gridcell')[5]); // row 2, `total` — empty string
    expect(panel).toHaveTextContent('(empty)');
  });

  it('is read-only, keyboard-reachable and does not trap focus', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await chooseExplorationOption(user, 'Value');

    const value = await screen.findByRole('textbox', {name: /^Value of/});
    expect(value).toHaveAttribute('readonly');
    expect(value).not.toBeDisabled();

    // Tab moves ON, out of the panel — a side surface, not a modal over the grid.
    value.focus();
    await user.tab();
    expect(value).not.toHaveFocus();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('complementary', {name: 'Value'})).not.toBeInTheDocument());
  });

  it('remembers being open, per tab', async () => {
    seedTab({valuePanelOpen: true});
    render();

    expect(await screen.findByRole('complementary', {name: 'Value'})).toBeInTheDocument();
  });
});

// ─── One presentation: the table ─────────────────────────────────────────────

// Record used to open by default below `tablet`, and Text was a third choice. Both are gone: the
// table is shown at every width, and a tab stored while they existed opens as the table with the
// rest of its presentation intact.
describe('the table is the only presentation', () => {
  it('opens as the table below tablet', async () => {
    window.innerWidth = 400;
    render();

    expect(await screen.findByRole('grid')).toBeInTheDocument();
    expect(screen.getAllByRole('gridcell')).toHaveLength(ROWS.length * COLUMNS.length);
  });

  it('opens a tab stored in Record or Text as the table, keeping the rest of its presentation', async () => {
    seedTab({presentation: 'text', recordRowIndex: 2, hiddenColumns: ['note'], valuePanelOpen: true});
    render();

    expect(await screen.findByRole('grid')).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', {name: 'note'})).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', {name: 'total'})).toBeInTheDocument();
    expect(screen.getByRole('complementary', {name: 'Value'})).toBeInTheDocument();
  });
});
