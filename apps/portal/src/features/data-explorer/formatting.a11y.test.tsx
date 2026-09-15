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
import type {ExplorationTabsState} from './dataExplorer.types';
import {chooseExplorationOption} from './explorationOptions.testkit';

// SPEC-184 FR-002 AC8. **Axe carries half of that criterion and cannot carry the other
// half**: `color-contrast` is disabled in `test/axe.ts` because jsdom has no layout engine
// to compute a rendered colour from, so contrast is proved by computation over the palette
// in `formatting.test.ts` and everything else about a coloured grid is proved here. Saying
// "the axe pass is green" about contrast would be a claim this tool never makes.
//
// Every check drives the surface first and hands the ALREADY-RENDERED container to axe: a
// dialog that has to be opened by a click cannot be reached by `expectNoA11yViolations`,
// which renders and checks in one step and would silently pass over the closed state.

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
  {name: 'qty', type: 'bigint'}
];
const ROWS: (string | null)[][] = [
  ['a', 'ok', '10'],
  ['a', 'failed', '20'],
  ['b', 'ok', null]
];

function seedTab() {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [{id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}}],
    activeTabId: 't1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
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
    ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 1, engineExecutionTimeMillis: 1}) as never
  );
  vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: ROWS}) as never);
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the formatting surfaces are accessible', () => {
  it('the Colours dialog, with a rule in both of its shapes', async () => {
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    const {container} = renderWithProviders(<DataExplorerWorkspace />, {
      route: '/explore',
      auth: authenticated('alice')
    });
    await screen.findByRole('columnheader', {name: 'status'});

    await chooseExplorationOption(user, 'Colors');
    const dialog = screen.getByRole('dialog', {name: 'Colors'});
    // A match rule and a gradient rule render DIFFERENT controls, so one of each is what
    // it takes to have every control in this dialog on screen at once.
    await user.click(within(dialog).getByRole('button', {name: 'Add rule'}));
    await user.click(within(dialog).getByRole('button', {name: 'Add rule'}));
    await user.click(within(dialog).getByRole('checkbox', {name: 'Rule 2 shades a number range'}));

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('a grid carrying colours, a type tint and bands', async () => {
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    const {container} = renderWithProviders(<DataExplorerWorkspace />, {
      route: '/explore',
      auth: authenticated('alice')
    });
    await screen.findByRole('columnheader', {name: 'status'});

    await chooseExplorationOption(user, 'Colors');
    const dialog = screen.getByRole('dialog', {name: 'Colors'});
    await user.click(within(dialog).getByRole('button', {name: 'Add rule'}));
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 column'}), 'status');
    await user.type(within(dialog).getByRole('textbox', {name: 'Rule 1 value'}), 'ok');
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 background'}), 'Red tint');
    await user.click(within(dialog).getByRole('checkbox', {name: /data type/i}));
    await user.click(within(dialog).getByRole('checkbox', {name: 'id'}));
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(screen.queryByRole('dialog', {name: 'Colors'})).not.toBeInTheDocument());
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('the Transformers dialog, with all three kinds on screen at once', async () => {
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    const {container} = renderWithProviders(<DataExplorerWorkspace />, {
      route: '/explore',
      auth: authenticated('alice')
    });
    await screen.findByRole('columnheader', {name: 'status'});

    await chooseExplorationOption(user, 'Transformers');
    const dialog = screen.getByRole('dialog', {name: 'Transformers'});
    // Each kind renders its own controls, so one of each is what it takes to have every
    // control in this dialog on screen.
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Show qty as'}), 'numeric');
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Show id as'}), 'binary');
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Show status as'}), 'url');

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('a grid and a Record view rendering links', async () => {
    // The gap that hid a real defect: an anchor inside the Record view's per-value BUTTON
    // is nested interactive content, and no earlier check rendered a transformed cell at
    // all. Both views are walked here, in one pass each.
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({
        columns: [{name: 'link', type: 'varchar'}],
        rows: [['https://example.com/a'], ['javascript:alert(1)']]
      }) as never
    );
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    const {container} = renderWithProviders(<DataExplorerWorkspace />, {
      route: '/explore',
      auth: authenticated('alice')
    });
    await screen.findByRole('columnheader', {name: 'link'});

    await chooseExplorationOption(user, 'Transformers');
    const dialog = screen.getByRole('dialog', {name: 'Transformers'});
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Show link as'}), 'url');
    await user.clear(within(dialog).getByRole('textbox', {name: 'Link for link'}));
    await user.type(within(dialog).getByRole('textbox', {name: 'Link for link'}), '${{value}');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));
    await waitFor(() => expect(screen.getAllByRole('link')).toHaveLength(1));

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);

    await user.click(screen.getByRole('button', {name: 'Record'}));
    await screen.findByRole('button', {name: 'Show the full value of link'});
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});
