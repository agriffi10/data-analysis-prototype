import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {useLocation} from 'react-router';
import {
  editor,
  installWorkspaceMocks,
  mockGetResults,
  ok,
  queueRuns,
  resetViewport,
  runScriptSingle,
  runScriptTabs,
  seedSingle,
  statusMap
} from '../../test/queryWorkspaceSupport';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {FEATURE_FLAG_DEFAULTS, featureFlagKeys} from '../feature-flags';
import {configValue} from '../../lib/runtimeConfig';
import {buildExploreSqlHandoff} from '../../lib/routeHandoff';
import {UNNAMED_COLUMNS_REFUSAL} from './exploreResult';
import {statementHint} from './query.sql';
import {QueryWorkspace} from './QueryWorkspace';

// *Explore in Data Explorer* on a Query result: offered on Save's terms for a statement the
// Explorer can wrap, refused with a reason for columns it cannot name, and handing the statement
// over in router state — never the URL.

vi.mock('./SqlEditor', () => import('../../test/sqlEditorStub'));

// ── AWS service boundary (the only real seam) ────────────────────────────────
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getTableDdl: vi.fn(),
  runStatementToCompletion: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn(),
  getQueryRowCount: vi.fn()
}));

vi.mock('../catalog/glue.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/glue.service')>()),
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));

vi.mock('./queryHistory.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./queryHistory.service')>()),
  getQueryHistory: vi.fn(),
  appendQueryHistory: vi.fn(),
  updateQueryHistoryEntry: vi.fn()
}));

vi.mock('../saved-queries/savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../saved-queries/savedQueries.service')>()),
  // The name/key helpers stay REAL — a tab label and a list row must not be able to
  // disagree about what a file is called, and a mocked `savedQueryName` would hide it.
  ensureSavedQueriesFolder: vi.fn(),
  listSavedQueries: vi.fn(),
  readSavedQuery: vi.fn(),
  writeSavedQuery: vi.fn(),
  deleteSavedQuery: vi.fn()
}));

vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));

vi.mock('../file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../file-browser/fileBrowser.service')>()),
  copyObject: vi.fn(),
  listFiles: vi.fn(),
  objectExists: vi.fn()
}));

vi.mock('../table-share/tableShare.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-share/tableShare.service')>()),
  enqueueTableShare: vi.fn()
}));

vi.mock('../table-builder/tableBuild.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-builder/tableBuild.service')>()),
  enqueueTableRefresh: vi.fn()
}));

const EXPLORE = 'Explore in Data Explorer';
const SELECT = 'SELECT name, qty FROM db.orders';

/** Where the app is, and the state it arrived with. */
function LocationStateProbe() {
  const location = useLocation();
  return (
    <output aria-label="probe-location">
      {JSON.stringify({path: `${location.pathname}${location.search}`, state: location.state})}
    </output>
  );
}

function probed(): {path: string; state: unknown} {
  return JSON.parse(screen.getByLabelText('probe-location').textContent ?? '{}') as {path: string; state: unknown};
}

function render(options: {explorerOn?: boolean} = {}) {
  const client = createTestQueryClient();
  client.setQueryDefaults(featureFlagKeys.all, {gcTime: Infinity, staleTime: Infinity});
  client.setQueryData(featureFlagKeys.resolved(configValue('environment')), {
    ...FEATURE_FLAG_DEFAULTS,
    dataExplorer: options.explorerOn ?? true
  });
  return renderWithProviders(
    <>
      <QueryWorkspace />
      <LocationStateProbe />
    </>,
    {auth: authenticated('alice'), route: '/query', queryClient: client, seedFeatureFlags: false}
  );
}

function columns(...names: string[]) {
  mockGetResults.mockResolvedValue(ok({columns: names.map((name) => ({name, type: 'string'})), rows: [names]}));
}

async function runStatement(user: ReturnType<typeof render>['user']) {
  await user.click(screen.getByRole('button', {name: 'Run statement'}));
}

/** Waits for Save, which shares the explore control's gate on the result, so an absence is judged after it. */
async function saveOffered() {
  return screen.findByRole('button', {name: 'Save results…'});
}

/**
 * The control never appears. Judged by waiting rather than by one `queryBy`, which passes on the
 * render before the results arrive — exactly when a broken gate still looks correct.
 */
async function expectExploreNeverAppears() {
  await expect(screen.findByRole('button', {name: EXPLORE}, {timeout: 400})).rejects.toThrow(/Unable to find/);
}

describe('Explore in Data Explorer', () => {
  beforeEach(installWorkspaceMocks);
  afterEach(resetViewport);

  it('hands a succeeded SELECT to the Explorer in router state, and offers nothing for SHOW TABLES', async () => {
    queueRuns('q-1', 'q-2');
    columns('tab_name');
    seedSingle('SHOW TABLES IN db;');
    const {user} = render();
    await screen.findByLabelText('SQL editor');

    await runStatement(user);
    await saveOffered();
    expect(screen.queryByRole('button', {name: EXPLORE})).not.toBeInTheDocument();

    columns('name', 'qty');
    await user.clear(editor());
    await user.type(editor(), `${SELECT};`);
    await runStatement(user);
    const explore = await screen.findByRole('button', {name: EXPLORE});
    // The statement handed over is the one whose result is on screen, not the buffer as it is now.
    await user.type(editor(), ' -- edited since');
    await user.click(explore);

    expect(probed()).toEqual({
      path: '/explore',
      state: buildExploreSqlHandoff({body: SELECT, label: statementHint(SELECT)})
    });
  });

  it('follows the displayed result tab, and Run Query Tab offers it too', async () => {
    queueRuns('q-1', 'q-2', 'q-3');
    columns('a');
    seedSingle('SELECT 1 AS a;\nDESCRIBE db.t;');
    const {user} = render();
    await screen.findByLabelText('SQL editor');

    await runScriptTabs(user);
    const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
    await saveOffered();
    // Tab 2, the DESCRIBE, is displayed: a result grid, but not a statement the Explorer can wrap.
    expect(within(strip).getAllByRole('tab')[1]).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('button', {name: EXPLORE})).not.toBeInTheDocument();
    await user.click(within(strip).getAllByRole('tab')[0]);
    expect(await screen.findByRole('button', {name: EXPLORE})).toBeInTheDocument();

    queueRuns('q-4');
    await user.clear(editor());
    await user.type(editor(), 'SELECT 1 AS a;');
    await runScriptSingle(user);
    await waitFor(() => expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument());
    expect(await screen.findByRole('button', {name: EXPLORE})).toBeInTheDocument();
  });

  it('hands over the statement behind the displayed tab when an earlier statement made no tab', async () => {
    // The INSERT earns no result tab, so a tab's position and its statement's position differ.
    queueRuns('q-1', 'q-2', 'q-3');
    columns('y');
    seedSingle('INSERT INTO db.t VALUES (1);\nSELECT a AS x FROM db.t;\nSELECT b AS y FROM db.u;');
    const {user} = render();
    await screen.findByLabelText('SQL editor');

    await runScriptTabs(user);
    const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
    expect(within(strip).getAllByRole('tab')[1]).toHaveAttribute('aria-selected', 'true');
    await user.click(await screen.findByRole('button', {name: EXPLORE}));

    expect(probed().state).toEqual(
      buildExploreSqlHandoff({body: 'SELECT b AS y FROM db.u', label: statementHint('SELECT b AS y FROM db.u')})
    );
  });

  it('is offered beside Save when a later statement failed, and not for a lone failure or while running', async () => {
    queueRuns('q-1', 'q-2');
    columns('a');
    statusMap['q-2'] = {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'};
    seedSingle('SELECT 1 AS a;\nSELEC 2;');
    const {user} = render();
    const ta = (await screen.findByLabelText('SQL editor')) as HTMLTextAreaElement;

    ta.setSelectionRange(0, ta.value.length);
    await runStatement(user);
    expect(await screen.findByText('Failed')).toBeInTheDocument();
    expect(await screen.findByRole('button', {name: EXPLORE})).toBeInTheDocument();

    queueRuns('q-3');
    statusMap['q-3'] = {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'};
    await user.clear(editor());
    await user.type(editor(), 'SELEC 3;');
    await runStatement(user);
    await waitFor(() => expect(screen.queryByRole('button', {name: 'Save results…'})).not.toBeInTheDocument());
    await expectExploreNeverAppears();

    queueRuns('q-4');
    statusMap['q-4'] = {state: 'RUNNING'};
    await user.clear(editor());
    await user.type(editor(), 'SELECT 2 AS b;');
    await runStatement(user);
    expect(await screen.findByText('Running…')).toBeInTheDocument();
    await expectExploreNeverAppears();
  });

  it.each([
    ['an unnamed expression', ['_col0', 'name']],
    ['two names that differ only by case', ['id', 'ID']]
  ])('refuses a result with %s, saying to add AS', async (_case, names) => {
    queueRuns('q-1');
    columns(...names);
    seedSingle('SELECT 1;');
    const {user} = render();
    await screen.findByLabelText('SQL editor');

    await runStatement(user);
    const button = await screen.findByRole('button', {name: EXPLORE});
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).toHaveAccessibleDescription(UNNAMED_COLUMNS_REFUSAL);
    await user.click(button);
    expect(probed().path).toBe('/query');
  });

  it('is not offered with the Data Explorer turned off, though Save is', async () => {
    queueRuns('q-1');
    columns('name');
    seedSingle(`${SELECT};`);
    const {user} = render({explorerOn: false});
    await screen.findByLabelText('SQL editor');

    await runStatement(user);
    await saveOffered();
    await expectExploreNeverAppears();
  });
});
