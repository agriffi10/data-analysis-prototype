import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {MemoryRouter, useLocation} from 'react-router';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {authValue, authenticated} from '../../test/authFixtures';
import {NavRailProvider} from '../../components/NavRailProvider';
import {useNavRailContent} from '../../components/navRailContext';
import {
  getQueryResults,
  getQueryStatus,
  getTableDdl,
  runQuery,
  runStatementToCompletion,
  stopQuery
} from '../catalog/athena.service';
import {getDatabase, listTables} from '../catalog/glue.service';
import {appendQueryHistory, getQueryHistory, updateQueryHistoryEntry} from './queryHistory.service';
import {
  deleteSavedQuery,
  ensureSavedQueriesFolder,
  listSavedQueries,
  readSavedQuery,
  savedQueryKey,
  savedQueryName,
  writeSavedQuery
} from '../saved-queries/savedQueries.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {copyObject, listFiles} from '../file-browser/fileBrowser.service';
import {enqueueTableRefresh} from '../table-builder/tableBuild.service';
import {enqueueTableShare} from '../table-share/tableShare.service';
import {QueryWorkspace} from './QueryWorkspace';
import {DEFAULT_RESULTS_PAGE_SIZE, QUERY_TABS_STORAGE_PREFIX} from './query.constants';
import {ROUTE_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {ToastProvider} from '../../components/ToastProvider';
import {AuthContext} from '../auth/authContext';
import {queryKeys} from './queryKeys';
import {savedQueryKeys} from '../saved-queries/savedQueryKeys';
import {catalogKeys} from '../catalog/catalogKeys';
import {connectionKeys} from '../connections/connectionKeys';
import type {QueryTabsState} from './query.types';
import type {QueryState} from '../catalog/catalog.types';
import type {ReactElement} from 'react';

// ─── from QueryWorkspace.test.tsx ───
vi.mock('./SqlEditor', async () => {
  const {forwardRef, useImperativeHandle, useRef} = await import('react');
  type MockProps = {
    value: string;
    onChange: (v: string) => void;
    onRun?: () => void;
    onRunScriptSingle?: () => void;
    onRunScriptTabs?: () => void;
  };
  return {
    SqlEditor: forwardRef<import('./SqlEditor').SqlEditorHandle, MockProps>(function MockSqlEditor(
      {value, onChange, onRun, onRunScriptSingle, onRunScriptTabs},
      ref
    ) {
      const taRef = useRef<HTMLTextAreaElement>(null);
      useImperativeHandle(ref, () => ({
        focus: () => taRef.current?.focus(),
        getSelectionRange: () => {
          const ta = taRef.current;
          if (!ta || ta.selectionStart === ta.selectionEnd) return null;
          return {start: ta.selectionStart, end: ta.selectionEnd};
        },
        getCursorOffset: () => taRef.current?.selectionStart ?? 0
      }));
      return (
        <>
          <textarea
            ref={taRef}
            aria-label="SQL editor"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          {/* Named in SPEC-078's vocabulary. Present only when the prop is wired, so
              an unwired scope is an absent button rather than a dead one. */}
          {onRun && <button onClick={onRun}>editor: Run Statement</button>}
          {onRunScriptSingle && <button onClick={onRunScriptSingle}>editor: Run Script → single result</button>}
          {onRunScriptTabs && <button onClick={onRunScriptTabs}>editor: Run Script → tab per statement</button>}
        </>
      );
    })
  };
});

// ── AWS service boundary (the only real seam) ────────────────────────────────
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getTableDdl: vi.fn(),
  runStatementToCompletion: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn()
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
  listFiles: vi.fn()
}));

vi.mock('../table-share/tableShare.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-share/tableShare.service')>()),
  enqueueTableShare: vi.fn()
}));

vi.mock('../table-builder/tableBuild.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-builder/tableBuild.service')>()),
  enqueueTableRefresh: vi.fn()
}));

vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}}),
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'id-token'})
}));

describe('QueryWorkspace', () => {
  // Integration style (react.md §21): render the REAL QueryWorkspace tree — real
  // hooks (useQueryTabs/useConnections/useSchema/useQueryExecution/useQueryResults/
  // useQueryHistory/useSavedQueries/useResultsPageSize/useResultRowCount/…) and real
  // child components (SchemaBrowser/DatabaseNode/TableActionsMenu/QueryTabStrip/
  // QueryStatusBar/QueryResultsTable/SaveResultsDialog/DestinationPicker/dialogs/
  // drawers) — mocking ONLY the AWS service boundary. Pure helpers in
  // query.service (parseS3Url/isTerminalState) and query.sql stay real via
  // importActual so the real hooks and split/resolve logic behave normally.

  // The Monaco editor is heavy/global (its own SqlEditor.test covers it) — stub the
  // lazy wrapper with a textarea that still drives value/onChange and forwards the
  // SPEC-078 selection handle so statement-resolution tests can position a cursor.
  // This is the sanctioned §21 heavy-child exception: Monaco needs a real DOM editor
  // and workers, which jsdom has neither of.
  //
  // SPEC-150 FR-010 widened its surface. It used to type only `{value, onChange}`, so
  // the three SPEC-078 run props were silently discarded and deleting one at the call
  // site changed nothing any test could see. It now accepts them and exposes each as a
  // button, which keeps the stub honest about the contract it stands in for — the
  // keybindings themselves stay SqlEditor.test's subject, not this file's.

  // copyObject = Save-results copy; listFiles = the SaveResultsDialog's real
  // DestinationPicker folder listing.

  const mockRunQuery = vi.mocked(runQuery);
  const mockStopQuery = vi.mocked(stopQuery);
  const mockGetTableDdl = vi.mocked(getTableDdl);
  const mockRunToCompletion = vi.mocked(runStatementToCompletion);
  const mockGetStatus = vi.mocked(getQueryStatus);
  const mockGetResults = vi.mocked(getQueryResults);
  const mockListTables = vi.mocked(listTables);
  const mockGetHistory = vi.mocked(getQueryHistory);
  const mockAppend = vi.mocked(appendQueryHistory);
  const mockUpdate = vi.mocked(updateQueryHistoryEntry);
  const mockListSaved = vi.mocked(listSavedQueries);
  const mockReadSaved = vi.mocked(readSavedQuery);
  const mockWriteSaved = vi.mocked(writeSavedQuery);
  const mockDeleteSaved = vi.mocked(deleteSavedQuery);
  const mockReadCache = vi.mocked(readSharedConnectionsCache);
  const mockCopyObject = vi.mocked(copyObject);
  const mockListFiles = vi.mocked(listFiles);
  const mockEnqueueRefresh = vi.mocked(enqueueTableRefresh);
  const mockEnqueueShare = vi.mocked(enqueueTableShare);

  // SaveResultsDialog and the space resolver read these at render/module time. Still load-bearing:
  // removing the user-space stub fails 18 of the tests below.
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bucket');

  const ok = <T,>(data: T) => ({success: true as const, data});
  const fail = (message: string, code?: string) => ({
    success: false as const,
    error: {message, ...(code ? {code} : {})}
  });

  // ── Builders ────────────────────────────────────────────────────────────────
  /** One `.sql` object in a space's `saved_queries/` folder (SPEC-173). */
  const savedFile = (
    name: string,
    over: {spaceId?: string; bucket?: string; size?: number; updatedAt?: string} = {}
  ) => ({
    spaceId: over.spaceId ?? 'personal',
    bucket: over.bucket ?? 'user-bucket',
    key: `alice/saved_queries/${name}.sql`,
    name,
    updatedAt: over.updatedAt ?? '2026-07-01T10:00:00.000Z',
    size: over.size ?? 24
  });
  const savedListing = (...names: string[]) => ok({queries: names.map((n) => savedFile(n)), isTruncated: false});
  const salesTable = {name: 'sales_2026', location: 's3://b/alice/sales/', columns: [{name: 'region', type: 'string'}]};
  const foreignTable = {name: 'foreign', location: 's3://b/bob/x/', columns: []};
  const viewObj = {name: 'revenue_view', tableType: 'VIRTUAL_VIEW', columns: []};

  /** Per-execution status overrides consulted by the getQueryStatus mock (live). */
  let statusMap: Record<string, {state?: QueryState; stateChangeReason?: string}> = {};
  const succeeded = (id: string, over: {state?: QueryState; stateChangeReason?: string} = {}) => ({
    queryExecutionId: id,
    state: 'SUCCEEDED' as QueryState,
    dataScannedBytes: 2048,
    engineExecutionTimeMillis: 800,
    outputLocation: `s3://user-bucket/alice/athenaresults/${id}.csv`,
    ...over
  });

  const rowsPage = {
    columns: [{name: 'region', type: 'string'}],
    rows: [['us-east'], ['eu-west']],
    nextToken: undefined
  };

  function seedTabs(state: QueryTabsState) {
    sessionStorage.setItem(`${QUERY_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
  }
  function seedSingle(sql: string) {
    seedTabs({version: 1, tabs: [{id: 'a', label: 'Query 1', sql}], activeTabId: 'a', nextQueryNumber: 2});
  }

  /** runQuery returns a distinct execution id per statement in a batch. */
  function queueRuns(...ids: string[]) {
    mockRunQuery.mockReset();
    for (const id of ids) mockRunQuery.mockResolvedValueOnce(ok({queryExecutionId: id}));
  }

  /** Renders whatever the page registered for the mobile nav drawer (SPEC-100 FR-005). */
  function NavRailProbe() {
    return <div aria-label="mobile nav rail">{useNavRailContent()}</div>;
  }

  /** A probe that surfaces the router location so navigation is observable without
   *  mocking react-router (everything stays real). */
  function LocationProbe() {
    const loc = useLocation();
    return <span aria-label="probe-location">{`${loc.pathname}${loc.search}`}</span>;
  }

  function renderWorkspace(route?: string, options: {queryClient?: QueryClient} = {}) {
    return renderWithProviders(
      <>
        <QueryWorkspace />
        <LocationProbe />
      </>,
      {auth: authenticated('alice'), route, ...options}
    );
  }

  const editor = () => screen.getByLabelText('SQL editor') as HTMLTextAreaElement;

  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    localStorage.clear();
    statusMap = {};

    mockReadCache.mockResolvedValue(ok({version: 1, connections: []}));
    mockGetDatabase();
    mockListTables.mockResolvedValue(ok([salesTable, foreignTable, viewObj]));
    mockGetHistory.mockResolvedValue(ok({version: 1, entries: []}));
    mockListSaved.mockResolvedValue(ok({queries: [], isTruncated: false}));
    mockAppend.mockResolvedValue(ok({version: 1, entries: []}));
    mockUpdate.mockResolvedValue(ok({version: 1, entries: []}));
    mockWriteSaved.mockImplementation(async ({space, name, sql}) =>
      ok(savedFile(name, {spaceId: space.id, bucket: space.bucket, size: sql.length}))
    );
    mockReadSaved.mockResolvedValue(ok('SELECT 1;'));
    mockDeleteSaved.mockResolvedValue(ok(undefined));
    vi.mocked(ensureSavedQueriesFolder).mockResolvedValue(ok(undefined));
    mockRunQuery.mockResolvedValue(ok({queryExecutionId: 'q-1'}));
    mockStopQuery.mockResolvedValue(ok(undefined));
    mockGetStatus.mockImplementation(async (id: string) => ok(succeeded(id, statusMap[id] ?? {})));
    mockGetResults.mockResolvedValue(ok(rowsPage));
    mockRunToCompletion.mockResolvedValue(ok(succeeded('q-run')));
    mockGetTableDdl.mockResolvedValue(ok('CREATE EXTERNAL TABLE ...'));
    mockCopyObject.mockResolvedValue(ok({destKey: 'alice/out.csv'}));
    mockListFiles.mockResolvedValue(ok({files: [], folders: [], isTruncated: false}));

    window.innerWidth = 1024;
  });

  afterEach(() => {
    window.innerWidth = 1024;
  });

  // getDatabase varies rarely — a helper so tests can override.
  function mockGetDatabase() {
    vi.mocked(getDatabase).mockImplementation(async (name: string) => ok({name}));
  }

  // Open the "More run options" split dropdown and pick a whole-script scope.
  async function runScriptSingle(user: ReturnType<typeof renderWorkspace>['user']) {
    await user.click(screen.getByRole('button', {name: 'More run options'}));
    await user.click(await screen.findByRole('menuitem', {name: 'Run Query Tab'}));
  }
  async function runScriptTabs(user: ReturnType<typeof renderWorkspace>['user']) {
    await user.click(screen.getByRole('button', {name: 'More run options'}));
    await user.click(await screen.findByRole('menuitem', {name: 'Run Multiple Queries'}));
  }

  // Open a rail table's kebab menu (the rail auto-expands the personal db).
  async function openTableMenu(user: ReturnType<typeof renderWorkspace>['user'], table: string) {
    await user.click(await screen.findByRole('button', {name: `Options for ${table}`}));
  }

  describe('QueryWorkspace', () => {
    it('renders the real schema rail + tabs and runs the active statement to a result set (SPEC-077 shape)', async () => {
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();

      // Real SchemaBrowser → DatabaseNode fetched sales_2026 from the mocked glue boundary.
      expect(await screen.findByRole('button', {name: 'sales_2026'})).toBeInTheDocument();
      await screen.findByLabelText('SQL editor');
      expect(screen.getByRole('tab', {name: /Query 1/})).toBeInTheDocument();
      // History + Saved queries hoisted to the global bar; Save stays per-tab.
      expect(screen.getByRole('button', {name: 'Saved queries'})).toBeInTheDocument();
      expect(screen.getAllByRole('button', {name: /History/})).toHaveLength(1);
      expect(screen.getByRole('button', {name: 'Save query'})).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      expect(await screen.findByText('Succeeded')).toBeInTheDocument();
      expect(await screen.findByText('us-east')).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(1);
      // No execution-database context — just sql + username (fully-qualified tables).
      expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: 'SELECT 1', username: 'alice'});
      expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('database');
      expect(mockAppend).toHaveBeenCalledWith('alice', expect.objectContaining({sql: 'SELECT 1'}));
    });

    // SPEC-150 FR-010. The keybindings themselves are SqlEditor.test's subject; what
    // this asserts is the other half — that the workspace actually HANDS the editor a
    // handler for each of SPEC-078's three scopes. Deleting one at the call site used
    // to change nothing any test could observe, because the stub discarded them.
    it('wires all three SPEC-078 run scopes into the editor', async () => {
      seedSingle('SELECT 1');
      renderWorkspace();
      await screen.findByLabelText('SQL editor');

      expect(screen.getByRole('button', {name: 'editor: Run Statement'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'editor: Run Script → single result'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'editor: Run Script → tab per statement'})).toBeInTheDocument();
    });

    it('de-dupes a rapid double-submit and keeps Clear/Run disabled while in flight [SPEC-083 FR-009]', async () => {
      seedSingle('SELECT 1');
      statusMap['q-1'] = {state: 'RUNNING'}; // stays in flight
      let resolveRun: (v: Awaited<ReturnType<typeof runQuery>>) => void = () => {};
      mockRunQuery.mockReturnValue(new Promise((resolve) => (resolveRun = resolve)));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      const run = screen.getByRole('button', {name: 'Run statement'});
      await user.click(run);
      await user.click(run); // second trigger before the run is recorded
      expect(mockRunQuery).toHaveBeenCalledTimes(1);

      resolveRun(ok({queryExecutionId: 'q-1'}));
      expect(await screen.findByRole('button', {name: /Stop/})).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('button', {name: 'Clear query'})).toBeDisabled();
    });

    it('surfaces a runQuery error in a danger banner and keeps Run available', async () => {
      seedSingle('SELECT bad');
      // `InvalidRequestException` is the name Athena actually returns for a rejected
      // StartQueryExecution, and it carries no code rule — so this exercises the ENGINE-MESSAGE
      // path, which is what the assertion below is about. (The bare `InvalidRequest` this used
      // to send is now one of the API's declared codes, and a code rule wins over a message
      // match by design.)
      mockRunQuery.mockResolvedValue(fail('COLUMN_NOT_FOUND: amont', 'InvalidRequestException'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      // SPEC-106: friendly, mapped guidance — never the raw Athena engine text.
      expect(await screen.findByText(/A column in your query wasn’t found/)).toBeInTheDocument();
      expect(screen.queryByText(/COLUMN_NOT_FOUND/)).not.toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Run statement'})).toBeInTheDocument();
    });

    it('restores tabs from persisted state on mount, showing the active tab', async () => {
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: 'SELECT one;'},
          {id: 'b', label: 'Scratch', sql: 'SELECT two;'}
        ],
        activeTabId: 'b',
        nextQueryNumber: 2
      });
      renderWorkspace();

      expect(await screen.findByLabelText('SQL editor')).toHaveValue('SELECT two;');
      expect(screen.getByRole('tab', {name: /Scratch/})).toHaveAttribute('aria-selected', 'true');
    });

    it('opens a new blank Query 2 tab and isolates text per tab', async () => {
      seedSingle('SELECT a');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      expect(editor()).toHaveValue('SELECT a');

      await user.click(screen.getByRole('button', {name: 'New query tab'}));
      expect(screen.getByRole('tab', {name: /Query 2/})).toBeInTheDocument();
      expect(editor()).toHaveValue(''); // a blank second tab
      await user.type(editor(), 'SELECT b');

      await user.click(screen.getByRole('tab', {name: /Query 1/}));
      expect(editor()).toHaveValue('SELECT a');
      await user.click(screen.getByRole('tab', {name: /Query 2/}));
      expect(editor()).toHaveValue('SELECT b');
    });

    it('closes an empty tab immediately but confirms a non-empty one', async () => {
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: 'SELECT keep;'},
          {id: 'b', label: 'Query 2', sql: ''},
          {id: 'c', label: 'Query 3', sql: 'SELECT bye;'}
        ],
        activeTabId: 'a',
        nextQueryNumber: 4
      });
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByTitle('Close Query 2'));
      expect(screen.queryByRole('tab', {name: /Query 2/})).not.toBeInTheDocument();

      await user.click(screen.getByTitle('Close Query 3'));
      const dialog = await screen.findByRole('alertdialog', {name: /confirm close tab/i});
      await user.click(within(dialog).getByRole('button', {name: 'Close tab'}));
      expect(screen.queryByRole('tab', {name: /Query 3/})).not.toBeInTheDocument();
    });

    it('shows the tab-limit dialog at the cap and opens no further tab', async () => {
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      const newTab = screen.getByRole('button', {name: 'New query tab'});
      for (let i = 0; i < 9; i++) await user.click(newTab);
      expect(screen.getAllByRole('tab')).toHaveLength(10);

      await user.click(newTab);
      expect(screen.getByRole('alertdialog', {name: /query tab limit reached/i})).toBeInTheDocument();
      expect(screen.getAllByRole('tab')).toHaveLength(10);
    });

    // --- saved queries (SPEC-173: files, not a JSON store) ---

    it('saves a new query: prompts, writes a .sql file, links + relabels the active tab', async () => {
      seedSingle('SELECT r;');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Save query'}));
      const dialog = screen.getByRole('dialog', {name: 'Save query'});
      await user.type(within(dialog).getByLabelText('Name'), 'My report');
      await user.click(within(dialog).getByRole('button', {name: 'Save'}));

      expect(mockWriteSaved).toHaveBeenCalledWith(
        expect.objectContaining({
          space: expect.objectContaining({id: 'personal', rootPrefix: 'alice/'}),
          name: 'My report',
          sql: 'SELECT r;',
          overwrite: false
        })
      );
      expect(await screen.findByRole('tab', {name: /My report/})).toBeInTheDocument();
    });

    it('turns a write COLLISION into a replace confirm, and only then overwrites', async () => {
      // FR-004: the collision is a HEAD on the exact key inside the write, because a scan
      // of the loaded list stopped being sound once it is paginated and the target space
      // may not be the one on screen.
      seedSingle('SELECT r;');
      // Models the real service: the key exists, so every non-overwrite write collides and
      // only an explicit Replace gets through. A single `…Once` would let the second
      // attempt succeed and quietly skip the half this test exists for.
      mockWriteSaved.mockImplementation(async ({space, name, sql, overwrite}) =>
        overwrite
          ? ok(savedFile(name, {spaceId: space.id, bucket: space.bucket, size: sql.length}))
          : fail(`“${name}” already exists.`, 'Collision')
      );
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Save query'}));
      await user.type(within(screen.getByRole('dialog', {name: 'Save query'})).getByLabelText('Name'), 'My report');
      await user.click(within(screen.getByRole('dialog', {name: 'Save query'})).getByRole('button', {name: 'Save'}));

      const confirm = await screen.findByRole('alertdialog', {name: /confirm replace saved query/i});
      expect(mockWriteSaved).toHaveBeenCalledTimes(1);
      expect(mockWriteSaved).toHaveBeenLastCalledWith(expect.objectContaining({overwrite: false}));

      // Backing out returns the user to what they TYPED, not to an empty field.
      await user.click(within(confirm).getByRole('button', {name: 'Cancel'}));
      expect(within(screen.getByRole('dialog', {name: 'Save query'})).getByLabelText('Name')).toHaveValue('My report');

      await user.click(within(screen.getByRole('dialog', {name: 'Save query'})).getByRole('button', {name: 'Save'}));
      const confirmAgain = await screen.findByRole('alertdialog', {name: /confirm replace saved query/i});
      await user.click(within(confirmAgain).getByRole('button', {name: 'Replace'}));
      expect(mockWriteSaved).toHaveBeenLastCalledWith(expect.objectContaining({name: 'My report', overwrite: true}));
      expect(await screen.findByRole('tab', {name: /My report/})).toBeInTheDocument();
    });

    it('keeps the dialog OPEN on a write failure, with the name, the space and a mapped message', async () => {
      // SPEC-175 FR-006: the realistic failure is a shared space whose membership was
      // revoked mid-session, so the dialog has to survive it — the buffer is still
      // unsaved, and the user's next move is to pick another destination. The message is
      // `toUserMessage`'s, inline on the field, never raw AWS text (SPEC-106).
      seedSingle('SELECT r;');
      mockWriteSaved.mockResolvedValue(fail('nope', 'AccessDenied'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Save query'}));
      await user.type(within(screen.getByRole('dialog', {name: 'Save query'})).getByLabelText('Name'), 'My report');
      await user.click(within(screen.getByRole('dialog', {name: 'Save query'})).getByRole('button', {name: 'Save'}));

      const dialog = await screen.findByRole('dialog', {name: 'Save query'});
      expect(await within(dialog).findByText(/don't have permission/i)).toBeInTheDocument();
      expect(within(dialog).getByLabelText('Name')).toHaveValue('My report');
      expect(within(dialog).getByLabelText('Space')).toBeEnabled();
      expect(screen.queryByText('nope')).not.toBeInTheDocument();
      // No toast claims success, and the tab is neither relabelled nor linked.
      expect(screen.queryByText(/^Saved “/)).not.toBeInTheDocument();
      expect(screen.queryByRole('tab', {name: /My report/})).not.toBeInTheDocument();
    });

    it('holds the saved_queries/ folder open when the workspace mounts, without blocking it', async () => {
      vi.mocked(ensureSavedQueriesFolder).mockResolvedValue(fail('no', 'AccessDenied'));
      renderWorkspace();

      // The editor still renders: FR-001's marker is best effort, because writing a
      // saved query creates the prefix on its own.
      await screen.findByLabelText('SQL editor');
      await waitFor(() =>
        expect(ensureSavedQueriesFolder).toHaveBeenCalledWith(expect.objectContaining({rootPrefix: 'alice/'}))
      );
    });

    it('shows a dirty marker once a tab’s buffer diverges from the file it was opened from', async () => {
      // A `.sql` object carries no body until it is READ, so the comparison is against
      // what this session last saw — the body fetched on open — rather than a `sql`
      // field on a list row that no longer exists.
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      mockReadSaved.mockResolvedValue(ok('SELECT original;'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      await user.click(await screen.findByRole('button', {name: /open saved query/i}));
      expect(screen.queryByLabelText('Unsaved changes')).not.toBeInTheDocument();

      await user.clear(editor());
      await user.type(editor(), 'SELECT edited;');

      expect(await screen.findByLabelText('Unsaved changes')).toBeInTheDocument();
    });

    it('opens a saved query with ONE GetObject, labels the tab by filename, and records it in history', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      mockReadSaved.mockResolvedValue(ok('SELECT 1;'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      // Merely opening the drawer fetches no bodies — the list is name/time/size only.
      expect(mockReadSaved).not.toHaveBeenCalled();

      await user.click(await screen.findByRole('button', {name: /open saved query/i}));
      expect(mockReadSaved).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('tab', {name: /Revenue/})).toBeInTheDocument();
      expect(editor()).toHaveValue('SELECT 1;');

      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
      expect(mockAppend).toHaveBeenCalledWith(
        'alice',
        expect.objectContaining({savedQueryKey: 'alice/saved_queries/Revenue.sql', savedQueryName: 'Revenue'})
      );
    });

    it('opens NO tab and says which file is gone when its body cannot be read', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      mockReadSaved.mockResolvedValue(fail('“Revenue” no longer exists.', 'SavedQueryNotFound'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      await user.click(await screen.findByRole('button', {name: /open saved query/i}));

      expect(await screen.findByText(/“Revenue” no longer exists/)).toBeInTheDocument();
      expect(screen.queryByRole('tab', {name: /Revenue/})).not.toBeInTheDocument();
      // The drawer is still open, because the user asked for this file.
      expect(screen.getByRole('button', {name: /open saved query/i})).toBeInTheDocument();
    });

    it('deletes a saved query (confirm) and deletes the OBJECT', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      await user.click(await screen.findByRole('button', {name: /delete saved query/i}));
      await user.click(
        within(screen.getByRole('alertdialog', {name: /confirm delete saved query/i})).getByRole('button', {
          name: 'Delete'
        })
      );

      expect(mockDeleteSaved).toHaveBeenCalledWith(
        expect.objectContaining({bucket: 'user-bucket', key: 'alice/saved_queries/Revenue.sql'})
      );
    });

    // ── SPEC-174: loading from a chosen space ──

    it('lists the CHOSEN space, remembers it, and opens a shared query into a tab linked to that space', async () => {
      mockReadCache.mockResolvedValue(
        ok({version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]})
      );
      mockListSaved.mockImplementation(async ({space}) =>
        space.id === 'teamspace'
          ? ok({
              queries: [
                {
                  spaceId: 'teamspace',
                  bucket: 'shared-bucket',
                  key: 'teamspace/saved_queries/Theirs.sql',
                  name: 'Theirs',
                  updatedAt: '2026-07-01T10:00:00.000Z',
                  size: 12
                }
              ],
              isTruncated: false
            })
          : savedListing('Mine')
      );
      mockReadSaved.mockResolvedValue(ok('SELECT shared;'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      expect(await screen.findByRole('button', {name: 'Open saved query Mine'})).toBeInTheDocument();

      await user.selectOptions(await screen.findByLabelText('Space'), 'teamspace');
      expect(await screen.findByRole('button', {name: 'Open saved query Theirs'})).toBeInTheDocument();
      // The previous space's rows do not persist into the new space's list.
      expect(screen.queryByRole('button', {name: 'Open saved query Mine'})).not.toBeInTheDocument();
      expect(sessionStorage.getItem('s3portal.query.savedQuerySpace.alice')).toBe('teamspace');

      await user.click(screen.getByRole('button', {name: 'Open saved query Theirs'}));
      expect(mockReadSaved).toHaveBeenCalledWith({bucket: 'shared-bucket', key: 'teamspace/saved_queries/Theirs.sql'});
      expect(await screen.findByRole('tab', {name: /Theirs/})).toBeInTheDocument();
      expect(editor()).toHaveValue('SELECT shared;');

      // FR-010, asserted for a SHARED space separately: editing changes a buffer, never
      // the object.
      const writesBefore = mockWriteSaved.mock.calls.length;
      await user.clear(editor());
      await user.type(editor(), 'SELECT edited;');
      expect(mockWriteSaved.mock.calls.length).toBe(writesBefore);

      // Re-opening it carries the FILE's stored body, not the edited buffer.
      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      await user.click(await screen.findByRole('button', {name: 'Open saved query Theirs'}));
      expect(screen.getAllByRole('tab', {name: /Theirs/})).toHaveLength(2);
      expect(editor()).toHaveValue('SELECT shared;');
    });

    // ── SPEC-175: saving into a chosen space ──

    /** A shared space the user is an active member of, for the save-destination tests. */
    function withSharedSpace() {
      mockReadCache.mockResolvedValue(
        ok({version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]})
      );
      // The real key builder, so a destination test cannot pass against a key the store
      // would never produce.
      mockWriteSaved.mockImplementation(async ({space, name, sql}) =>
        ok({
          spaceId: space.id,
          bucket: space.bucket,
          key: savedQueryKey(space.rootPrefix, name),
          name: savedQueryName(savedQueryKey(space.rootPrefix, name)),
          updatedAt: '2026-07-01T10:00:00.000Z',
          size: sql.length
        })
      );
    }

    /** Opens Save, picks a destination if asked, types a name and submits. */
    async function saveAs(user: ReturnType<typeof renderWorkspace>['user'], name: string, spaceId?: string) {
      await user.click(screen.getByRole('button', {name: 'Save query'}));
      const dialog = screen.getByRole('dialog', {name: 'Save query'});
      if (spaceId) await user.selectOptions(within(dialog).getByLabelText('Space'), spaceId);
      await user.clear(within(dialog).getByLabelText('Name'));
      await user.type(within(dialog).getByLabelText('Name'), name);
      await user.click(within(dialog).getByRole('button', {name: 'Save'}));
    }

    it('writes into the CHOSEN shared space, links the tab there, and remembers it', async () => {
      // FR-001/FR-002: the folder marker is ensured for the space being written to — not
      // for the personal one — and the ONE space memory the load surface reads is updated,
      // so the next save and the next load both open where the user last was.
      seedSingle('SELECT r;');
      withSharedSpace();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await screen.findByRole('button', {name: 'Save query'});

      await saveAs(user, 'Quarterly', 'teamspace');

      await waitFor(() =>
        expect(ensureSavedQueriesFolder).toHaveBeenCalledWith(
          expect.objectContaining({id: 'teamspace', bucket: 'shared-bucket', rootPrefix: 'teamspace/'})
        )
      );
      expect(mockWriteSaved).toHaveBeenCalledWith(
        expect.objectContaining({
          space: expect.objectContaining({id: 'teamspace', bucket: 'shared-bucket'}),
          name: 'Quarterly',
          sql: 'SELECT r;',
          overwrite: false
        })
      );
      expect(await screen.findByRole('tab', {name: /Quarterly/})).toBeInTheDocument();
      expect(await screen.findByText(/Saved “Quarterly” to teamspace/)).toBeInTheDocument();
      await waitFor(() => expect(sessionStorage.getItem('s3portal.query.savedQuerySpace.alice')).toBe('teamspace'));
    });

    it('re-saves a linked tab in place: one write, overwrite, and NO second confirm', async () => {
      // FR-004. The prompt already named the file being replaced, so confirming again asks
      // about the thing just answered.
      seedTabs({
        version: 1,
        tabs: [
          {
            id: 'a',
            label: 'Monthly',
            sql: 'SELECT edited;',
            savedQuery: {
              spaceId: 'personal',
              bucket: 'user-bucket',
              key: 'alice/saved_queries/Monthly.sql',
              name: 'Monthly'
            }
          }
        ],
        activeTabId: 'a',
        nextQueryNumber: 2
      });
      withSharedSpace();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Save query'}));
      await user.click(within(screen.getByRole('dialog', {name: 'Save query'})).getByRole('button', {name: 'Save'}));

      await waitFor(() => expect(mockWriteSaved).toHaveBeenCalledTimes(1));
      expect(mockWriteSaved).toHaveBeenCalledWith(
        expect.objectContaining({name: 'Monthly', sql: 'SELECT edited;', overwrite: true})
      );
      expect(screen.queryByRole('alertdialog', {name: /confirm replace saved query/i})).not.toBeInTheDocument();
      expect(screen.getByRole('tab', {name: /Monthly/})).toBeInTheDocument();
    });

    it('re-runs a history entry into the active tab (no database context)', async () => {
      mockGetHistory.mockResolvedValue(
        ok({
          version: 1,
          entries: [
            {
              queryExecutionId: 'old',
              sql: 'SELECT 42',
              database: 'alice',
              submittedAt: new Date().toISOString(),
              status: 'SUCCEEDED'
            }
          ]
        })
      );
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: /History/}));
      await user.click(await screen.findByRole('button', {name: /re-run this query/i}));

      expect(mockRunQuery).toHaveBeenCalledTimes(1);
      expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: 'SELECT 42', username: 'alice'});
    });

    // --- table actions (driven through the REAL rail menu) ---

    it('View source files navigates for an in-space table and is disabled for an out-of-space one', async () => {
      const {user} = renderWorkspace();
      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'View source files'}));
      expect(screen.getByLabelText('probe-location')).toHaveTextContent('/files?prefix=alice%2Fsales%2F');

      await openTableMenu(user, 'foreign');
      expect(await screen.findByRole('menuitem', {name: 'View source files'})).toBeDisabled();
    });

    it('View data opens a "{table}" tab and auto-runs a fully-qualified unbounded SELECT * (no LIMIT) [SPEC-105]', async () => {
      const {user} = renderWorkspace();
      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'View data'}));

      expect(await screen.findByRole('tab', {name: /sales_2026/})).toBeInTheDocument();
      expect(editor()).toHaveValue('SELECT * FROM alice.sales_2026');
      expect(mockRunQuery).toHaveBeenCalledWith(expect.objectContaining({sql: 'SELECT * FROM alice.sales_2026'}));
      expect(mockRunQuery.mock.calls.at(-1)?.[0].sql).not.toMatch(/limit/i);
    });

    it('Drop table confirms, runs DROP TABLE in the background (history + toast); a failure shows an error toast', async () => {
      const {user} = renderWorkspace();

      mockRunToCompletion.mockResolvedValueOnce(ok(succeeded('q-drop')));
      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'Drop table'}));
      await user.click(
        within(screen.getByRole('alertdialog', {name: /confirm drop table/i})).getByRole('button', {name: 'Drop table'})
      );

      expect(await screen.findByText('Dropped sales_2026')).toBeInTheDocument();
      // BACKTICKS: a DROP is DDL, which Athena parses with Hive — the mirror of CREATE VIEW
      // above, which is Trino and takes double quotes. The database is the identifier that
      // needs quoting: a shared space's name is format-checked by nothing server-side.
      expect(mockRunToCompletion).toHaveBeenCalledWith(
        expect.objectContaining({sql: 'DROP TABLE `alice`.`sales_2026`'})
      );
      expect(mockAppend).toHaveBeenCalledWith('alice', expect.objectContaining({queryExecutionId: 'q-drop'}));

      mockRunToCompletion.mockResolvedValueOnce(
        ok(succeeded('q-drop2', {state: 'FAILED', stateChangeReason: 'table locked'}))
      );
      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'Drop table'}));
      await user.click(
        within(screen.getByRole('alertdialog', {name: /confirm drop table/i})).getByRole('button', {name: 'Drop table'})
      );
      // SPEC-106: the toast shows friendly, mapped text — not the raw Athena reason.
      expect(await screen.findByText(/Couldn’t drop sales_2026/)).toBeInTheDocument();
      expect(screen.queryByText(/table locked/)).not.toBeInTheDocument();
    });

    it('Create view composes CREATE OR REPLACE VIEW (target db derived from the body), records history + success toast', async () => {
      seedSingle('SELECT region FROM alice.sales;');
      mockRunToCompletion.mockResolvedValue(ok(succeeded('q-view')));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Create view'}));
      const dialog = screen.getByRole('dialog', {name: 'Create view'});
      await user.type(within(dialog).getByLabelText('View name'), 'region_view');
      await user.click(within(dialog).getByRole('button', {name: 'Create'}));

      expect(await screen.findByText('Created view region_view')).toBeInTheDocument();
      expect(mockRunToCompletion).toHaveBeenCalledWith(
        expect.objectContaining({
          // Both identifiers are QUOTED, with the Trino escaper — Athena parses CREATE VIEW
          // with Trino, where double quotes are the identifier quote and a backtick is an
          // error. It matters because a shared space's name reaches the same builder and
          // nothing server-side checks that name's format.
          sql: 'CREATE OR REPLACE VIEW "alice"."region_view" AS SELECT region FROM alice.sales',
          database: 'alice',
          username: 'alice'
        })
      );
      expect(mockAppend).toHaveBeenCalledWith('alice', expect.objectContaining({queryExecutionId: 'q-view'}));
      expect(editor()).toHaveValue('SELECT region FROM alice.sales;'); // editor keeps the user's SELECT
    });

    // --- Save results to my files (real SaveResultsDialog + DestinationPicker) ---

    async function runToSucceeded(user: ReturnType<typeof renderWorkspace>['user']) {
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
    }
    async function saveInto(user: ReturnType<typeof renderWorkspace>['user'], filename: string) {
      await user.click(await screen.findByRole('button', {name: 'Save results to my files'}));
      const dialog = await screen.findByRole('dialog', {name: 'Save results to my files'});
      const nameInput = within(dialog).getByLabelText('File name');
      await user.clear(nameInput);
      await user.type(nameInput, filename);
      return dialog;
    }

    it('saves a succeeded result to the personal space (cross-checked copy + Files deep-link)', async () => {
      seedSingle('SELECT 1');
      mockCopyObject.mockResolvedValue(ok({destKey: 'alice/out.csv'}));
      const {user} = renderWorkspace();
      await runToSucceeded(user);

      const dialog = await saveInto(user, 'out');
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

      expect(mockCopyObject).toHaveBeenCalledWith({
        bucket: 'user-bucket',
        destBucket: 'user-bucket',
        sourceKey: 'alice/athenaresults/q-1.csv',
        destKey: 'alice/out.csv',
        username: 'alice',
        overwrite: false
      });
      await user.click(await screen.findByRole('button', {name: 'View in Files'}));
      expect(screen.getByLabelText('probe-location')).toHaveTextContent('/files?prefix=alice%2F');
    });

    it('a destination collision prompts Overwrite, then copies with overwrite', async () => {
      seedSingle('SELECT 1');
      mockCopyObject
        .mockResolvedValueOnce(fail('exists', 'Collision'))
        .mockResolvedValueOnce(ok({destKey: 'alice/out.csv'}));
      const {user} = renderWorkspace();
      await runToSucceeded(user);

      const dialog = await saveInto(user, 'out');
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

      await user.click(
        within(await screen.findByRole('alertdialog', {name: /confirm overwrite/i})).getByRole('button', {
          name: 'Overwrite'
        })
      );
      expect(mockCopyObject).toHaveBeenLastCalledWith(expect.objectContaining({overwrite: true}));
      expect(await screen.findByText(/Saved to alice\/out\.csv/)).toBeInTheDocument();
    });
  });

  describe('QueryWorkspace — multi-statement batches (SPEC-078)', () => {
    const THREE = 'SELECT 1; CREATE TABLE alice.t (id int); SELECT 2;';
    function seedScript(sql: string = THREE) {
      seedTabs({version: 1, tabs: [{id: 'a', label: 'Query 1', sql}], activeTabId: 'a', nextQueryNumber: 2});
    }

    it('runs a script sequentially and records one history entry per statement (FR-002/FR-003)', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptSingle(user);

      expect(await screen.findByText(/Script finished · 3 statements/)).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(3);
      expect(mockRunQuery.mock.calls.map((c) => c[0].sql)).toEqual([
        'SELECT 1',
        'CREATE TABLE alice.t (id int)',
        'SELECT 2'
      ]);
      expect(mockAppend).toHaveBeenCalledTimes(3);
      expect(mockAppend.mock.calls.map((c) => c[1].sql)).toEqual([
        'SELECT 1',
        'CREATE TABLE alice.t (id int)',
        'SELECT 2'
      ]);
      // Single-result scope → no per-statement result-tab strip.
      expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument();
    });

    it('stops at the first failed statement, names it, and reports the skipped remainder (FR-002/FR-004)', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      statusMap['q-2'] = {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'};
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptSingle(user);

      // SPEC-106: the position is named; the reason is friendly, mapped text.
      expect(await screen.findByText(/Statement 2 of 3 failed\. There’s a syntax error/)).toBeInTheDocument();
      expect(screen.getByText(/Statement 3 did not run/)).toBeInTheDocument();
      expect(screen.queryByText(/SYNTAX_ERROR/)).not.toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(2);
      expect(mockAppend).toHaveBeenCalledTimes(2);
    });

    it('Run Script (tab per statement) yields one result tab per result-producing statement, and a new run clears them (FR-007)', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptTabs(user);

      const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
      const resultTabs = within(strip).getAllByRole('tab');
      // The CREATE (statement 2) earns no tab; labels carry statement positions.
      expect(resultTabs.map((t) => t.textContent)).toEqual(['1 · SELECT 1', '3 · SELECT 2']);
      expect(resultTabs[1]).toHaveAttribute('aria-selected', 'true');
      await user.click(resultTabs[0]);
      expect(within(strip).getAllByRole('tab')[0]).toHaveAttribute('aria-selected', 'true');

      // A fresh run (with an in-flight last statement) clears the previous strip.
      queueRuns('q-4', 'q-5', 'q-6');
      statusMap['q-6'] = {state: 'RUNNING'};
      await runScriptTabs(user);
      await screen.findByRole('button', {name: /Stop/});
      expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument();
    });

    it('Run Statement executes the selection, else the statement under the cursor (FR-006)', async () => {
      queueRuns('q-1', 'q-2');
      seedScript('SELECT 1;\nSELECT 2;');
      const {user} = renderWorkspace();
      const ta = (await screen.findByLabelText('SQL editor')) as HTMLTextAreaElement;

      ta.setSelectionRange(0, 'SELECT 1'.length);
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await waitFor(() => expect(mockRunQuery).toHaveBeenCalledTimes(1));
      expect(mockRunQuery.mock.calls[0][0].sql).toBe('SELECT 1');
      await screen.findByText('Succeeded');

      const cursor = ta.value.indexOf('SELECT 2') + 3;
      ta.setSelectionRange(cursor, cursor);
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await waitFor(() => expect(mockRunQuery).toHaveBeenCalledTimes(2));
      expect(mockRunQuery.mock.calls[1][0].sql).toBe('SELECT 2');
    });
  });

  describe('QueryWorkspace — shared-space routing & save (SPEC-055/077)', () => {
    it('runs with no db/outputLocation and offers personal + shared save destinations', async () => {
      mockReadCache.mockResolvedValue(
        ok({version: 1, connections: [{name: 'salesdata', role: 'member', status: 'active'}]})
      );
      seedSingle('SELECT 1');
      mockCopyObject.mockResolvedValue(ok({destKey: 'salesdata/out.csv'}));
      const {user} = renderWorkspace();
      await screen.findByRole('button', {name: 'sales_2026'}); // rail loaded

      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
      // The run carries neither a database context nor a shared outputLocation.
      expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: 'SELECT 1', username: 'alice'});
      expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('outputLocation');

      await user.click(await screen.findByRole('button', {name: 'Save results to my files'}));
      const dialog = await screen.findByRole('dialog', {name: 'Save results to my files'});
      const spaceSelect = within(dialog).getByLabelText('Save to');
      expect(within(spaceSelect).getByRole('option', {name: 'My files'})).toBeInTheDocument();
      expect(within(spaceSelect).getByRole('option', {name: 'salesdata'})).toBeInTheDocument();

      await user.selectOptions(spaceSelect, 'salesdata');
      const nameInput = within(dialog).getByLabelText('File name');
      await user.clear(nameInput);
      await user.type(nameInput, 'out');
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

      // Cross-bucket copy from the personal results prefix into the shared space.
      expect(mockCopyObject).toHaveBeenCalledWith(
        expect.objectContaining({
          bucket: 'user-bucket',
          destBucket: 'shared-bucket',
          sourceKey: 'alice/athenaresults/q-1.csv',
          destKey: 'salesdata/out.csv',
          overwrite: false
        })
      );
      expect(await screen.findByText(/Saved to salesdata\/out\.csv/)).toBeInTheDocument();
      // The Files browser can't render shared spaces → no deep-link.
      expect(screen.queryByRole('button', {name: 'View in Files'})).not.toBeInTheDocument();
    });
  });

  // ── SPEC-145: refresh table ─────────────────────────────────────────────────
  describe('QueryWorkspace — refresh table (SPEC-145)', () => {
    const refreshDialog = () => screen.getByRole('alertdialog', {name: /confirm refresh table/i});

    beforeEach(() => {
      mockEnqueueRefresh.mockResolvedValue(ok(undefined));
    });

    it('enqueues a refresh from the rail menu and reports it as pending', async () => {
      const {user} = renderWorkspace();
      await user.click(await screen.findByRole('button', {name: 'Options for sales_2026'}));
      await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'Refresh table'}));

      const dialog = refreshDialog();
      expect(within(dialog).getByText('alice.sales_2026')).toBeInTheDocument();
      expect(within(dialog).getByText('s3://b/alice/sales/')).toBeInTheDocument();

      await user.click(within(dialog).getByRole('button', {name: 'Refresh table'}));

      // The space is derived from the table's own location (FR-004).
      expect(mockEnqueueRefresh).toHaveBeenCalledWith({
        space: {kind: 'personal', bucket: 'b', prefix: 'alice/sales/', database: 'alice'},
        tableName: 'sales_2026'
      });
      expect(await screen.findByText(/Refreshing “alice\.sales_2026”/)).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    });

    it('opens the link-borne dialog from a columns_removed notification link', async () => {
      const {user} = renderWorkspace('/query?refreshTable=alice.sales_2026&removed=legacy_id,Order%20ID');

      const dialog = await screen.findByRole('alertdialog', {name: /confirm refresh table/i});
      const named = within(dialog).getByRole('list', {name: /columns that would be removed/i});
      expect(within(named).getByText('legacy_id')).toBeInTheDocument();
      expect(within(named).getByText('Order ID')).toBeInTheDocument();

      // FR-003: confirm is gated on the opt-in in this state — since SPEC-186 FR-002 as an
      // `aria-disabled` refusal that says what it is waiting for, not a bare `disabled`.
      const confirm = within(dialog).getByRole('button', {name: 'Refresh table'});
      expect(confirm).toHaveAttribute('aria-disabled', 'true');
      await user.click(within(dialog).getByRole('checkbox', {name: /allow columns to be removed/i}));
      await user.click(confirm);

      expect(mockEnqueueRefresh).toHaveBeenCalledWith(expect.objectContaining({allowRemovals: true}));
    });
  });

  // ── SPEC-100: responsive workspace ──────────────────────────────────────────
  describe('QueryWorkspace responsive (SPEC-100)', () => {
    /** Renders inside a NavRailProvider so the mobile drawer's contextual slot is observable. */
    function renderMobileWorkspace() {
      window.innerWidth = 390;
      return renderWithProviders(
        <NavRailProvider>
          <QueryWorkspace />
          <NavRailProbe />
          <LocationProbe />
        </NavRailProvider>,
        {auth: authenticated('alice')}
      );
    }

    it('pares the workspace to a browse-first surface below tablet — no editor, toolbar or tab strip', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      renderMobileWorkspace();

      // Saved is the default surface (FR-004).
      expect(await screen.findByRole('button', {name: 'Run saved query Revenue'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Saved'})).toHaveAttribute('aria-pressed', 'true');

      expect(screen.queryByLabelText('SQL editor')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Run statement'})).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Clear query'})).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Create view'})).not.toBeInTheDocument();
      expect(screen.queryByRole('tablist', {name: 'Query tabs'})).not.toBeInTheDocument();
    });

    it('moves the schema rail off-canvas below tablet, and keeps it inline above', async () => {
      const {unmount} = renderMobileWorkspace();
      // Not in the inline layout…
      expect(screen.queryByRole('complementary', {name: 'Schema browser'})).not.toBeInTheDocument();
      // …but the same tree is handed to the mobile nav drawer's contextual slot.
      const rail = await screen.findByLabelText('mobile nav rail');
      expect(await within(rail).findByRole('button', {name: 'Collapse alice'})).toBeInTheDocument();
      expect(await within(rail).findByText('sales_2026')).toBeInTheDocument();
      unmount();

      window.innerWidth = 1024;
      renderWorkspace();
      expect(await screen.findByRole('complementary', {name: 'Schema browser'})).toBeInTheDocument();
    });

    it('runs a saved query from a card and shows row cards with a pager', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      // The card carries no SQL — the file is read when the card is CHOSEN (FR-006).
      mockReadSaved.mockResolvedValue(ok('SELECT region FROM alice.sales'));
      const {user} = renderMobileWorkspace();

      await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));

      // The shared run path, not a mobile-only one.
      await waitFor(() =>
        expect(mockRunQuery).toHaveBeenCalledWith({sql: 'SELECT region FROM alice.sales', username: 'alice'})
      );
      expect(await screen.findByRole('heading', {name: 'Revenue'})).toBeInTheDocument();
      // One card per row of the page, read-only SQL, and a fixed pager.
      expect(await screen.findByLabelText('Row 1')).toBeInTheDocument();
      expect(within(screen.getByLabelText('Row 1')).getByText('us-east')).toBeInTheDocument();
      expect(screen.queryByLabelText('SQL editor')).not.toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();

      // Back returns to the browse-first home.
      await user.click(screen.getByRole('button', {name: 'Back to queries'}));
      expect(await screen.findByRole('button', {name: 'Run saved query Revenue'})).toBeInTheDocument();
    });

    it('never shows one query’s results under another query’s name', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue', 'Costs'));
      const {user} = renderMobileWorkspace();

      await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));
      expect(await screen.findByLabelText('Row 1')).toBeInTheDocument();
      await user.click(screen.getByRole('button', {name: 'Back to queries'}));

      // The second run never reaches Athena, so no run is installed on the tab.
      mockRunQuery.mockResolvedValueOnce(fail('Rate exceeded', 'ThrottlingException'));
      await user.click(await screen.findByRole('button', {name: 'Run saved query Costs'}));

      expect(await screen.findByRole('heading', {name: 'Costs'})).toBeInTheDocument();
      expect(await screen.findByText('Query failed.')).toBeInTheDocument();
      // Costs' failure must not be dressed in Revenue's succeeded status or rows.
      expect(screen.queryByLabelText('Row 1')).not.toBeInTheDocument();
      expect(screen.queryByText('Succeeded')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Prev'})).not.toBeInTheDocument();
    });

    it('runs a table’s data from the drawer into the mobile results view', async () => {
      const {user} = renderMobileWorkspace();
      const rail = await screen.findByLabelText('mobile nav rail');

      await user.click(await within(rail).findByRole('button', {name: 'Options for sales_2026'}));
      await user.click(await screen.findByRole('menuitem', {name: 'View data'}));

      // On a phone there is no editor tab to open into — the run has to land
      // somewhere the user can see it.
      expect(await screen.findByRole('heading', {name: 'sales_2026'})).toBeInTheDocument();
      expect(await screen.findByLabelText('Row 1')).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledWith({sql: 'SELECT * FROM alice.sales_2026', username: 'alice'});
    });

    it('hands a tab back to the editor cleanly when the viewport grows past tablet', async () => {
      seedSingle('SELECT my_unsaved_draft');
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      const {user, rerender} = renderMobileWorkspace();

      await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));
      expect(await screen.findByLabelText('Row 1')).toBeInTheDocument();

      // Rotate/resize past the breakpoint: `useBreakpoint` re-reads the width on
      // the next render, so re-rendering the same tree crosses the tier.
      window.innerWidth = 1400;
      rerender(
        <NavRailProvider>
          <QueryWorkspace />
          <NavRailProbe />
        </NavRailProvider>
      );

      // The editor holds the draft, so it must not wear the mobile run's results —
      // nor claim the run returned nothing. The run itself is still in history.
      expect(await screen.findByLabelText('SQL editor')).toHaveValue('SELECT my_unsaved_draft');
      expect(screen.getByText('Run a query to see results.')).toBeInTheDocument();
      expect(screen.queryByText('The run finished without returning rows.')).not.toBeInTheDocument();
      expect(screen.queryByText('us-east')).not.toBeInTheDocument();
    });
  });

  // ── SPEC-154 FR-001: table share, driven end to end ─────────────────────────
  //
  // `enqueueTableShare` was mocked in this file and never asserted, and the flow's three
  // fragments each tested a stub: `TableShareDialog.test.tsx` asserted a `vi.fn()` prop,
  // `useTableShare.test.ts` was a bare `renderHook`, `DatabaseNode.test.tsx` asserted
  // `onShareTable` was called. Every half was green and the WIRE between them was untested — a
  // dialog that never mounts, a wrong `source`, or a dropped `onSubmit` all passed.
  //
  // Structured on the SPEC-145 refresh block above, deliberately: menu → dialog → submit →
  // service → toast, plus the failure path and the control's absence where it must not appear.
  describe('QueryWorkspace — share table (SPEC-093)', () => {
    async function openShareDialog(user: ReturnType<typeof renderWorkspace>['user'], table = 'sales_2026') {
      await openTableMenu(user, table);
      await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'Share table'}));
      return screen.getByRole('dialog', {name: `Share table ${table}`});
    }

    beforeEach(() => {
      mockEnqueueShare.mockResolvedValue(ok(undefined));
    });

    it('shares a table with two users from the rail menu and reports it as pending', async () => {
      const {user} = renderWorkspace();

      const dialog = await openShareDialog(user);
      // The DATABASE comes from the rail node, not from anywhere in the dialog (SPEC-077),
      // so it is worth seeing before the submit that carries it.
      expect(within(dialog).getByText('alice.sales_2026')).toBeInTheDocument();

      await user.type(within(dialog).getByLabelText('Usernames'), 'bob, cara');
      await user.click(within(dialog).getByRole('button', {name: 'Add'}));
      const chips = within(dialog).getByRole('list', {name: 'Recipients'});
      expect(within(chips).getByText('bob')).toBeInTheDocument();
      expect(within(chips).getByText('cara')).toBeInTheDocument();

      await user.click(within(dialog).getByRole('button', {name: 'Share'}));

      expect(mockEnqueueShare).toHaveBeenCalledWith({
        source: {database: 'alice', table: 'sales_2026'},
        tableName: 'sales_2026',
        recipients: [
          {kind: 'user', name: 'bob'},
          {kind: 'user', name: 'cara'}
        ]
      });
      expect(mockEnqueueShare).toHaveBeenCalledTimes(1);
      expect(await screen.findByText(/Sharing “alice\.sales_2026”/)).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByRole('dialog', {name: /Share table/})).not.toBeInTheDocument());
    });
  });

  // ── SPEC-154 FR-005: results pagination, and the seam it shares ─────────────
  //
  // `'Next'` did not appear anywhere in this file, and the fixture could not enable it —
  // `rowsPage` hard-codes `nextToken: undefined`, so the pager was permanently disabled and
  // every path through it was unreachable. Coverage was hook state plus a prop spy, which is
  // exactly the split this spec exists to close.
  describe('QueryWorkspace — results pagination (SPEC-087)', () => {
    const page = (rows: string[][], nextToken?: string) => ({
      columns: [{name: 'region', type: 'string'}],
      rows,
      nextToken
    });

    /** Two server pages: page 1 carries a token, page 2 ends the walk. */
    function seedTwoPages() {
      mockGetResults.mockImplementation(async ({nextToken}: {nextToken?: string}) =>
        nextToken === 't-2' ? ok(page([['ap-south']])) : ok(page([['us-east'], ['eu-west']], 't-2'))
      );
    }

    async function runOnce(user: ReturnType<typeof renderWorkspace>['user']) {
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
    }

    it('fetches page 2 with the NextToken and renders it', async () => {
      seedTwoPages();
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await runOnce(user);
      expect(await screen.findByText('us-east')).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'Next'}));

      expect(await screen.findByText('ap-south')).toBeInTheDocument();
      expect(screen.queryByText('us-east')).not.toBeInTheDocument();
      // The token is the whole mechanism — a Next that refetched page 1 would still "work"
      // visually on a fixture that returned the same rows twice.
      //
      // `maxRows` is load-bearing in this assertion, not decoration: `useResultRowCount` walks
      // every page of the same execution in the background through this same mock, threading
      // the token itself, so `objectContaining({nextToken: 't-2'})` alone is satisfied by the
      // row-count walker even if the pager never threads anything. The walker uses
      // ROW_COUNT_PAGE_SIZE; only the pager asks for the display page size.
      expect(mockGetResults).toHaveBeenCalledWith({
        queryExecutionId: 'q-1',
        nextToken: 't-2',
        maxRows: DEFAULT_RESULTS_PAGE_SIZE
      });
    });
  });

  // FR-005's neighbours: two settings that share the pagination seam — tested at hook level
  // and through a prop spy, never through a user path.
  describe('QueryWorkspace — result-view settings that survive a tab switch (SPEC-079/087)', () => {
    async function runOnce(user: ReturnType<typeof renderWorkspace>['user']) {
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
    }

    it('keeps a column width across a switch away from the results tab and back', async () => {
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: 'SELECT 1'},
          {id: 'b', label: 'Query 2', sql: 'SELECT 2'}
        ],
        activeTabId: 'a',
        nextQueryNumber: 3
      });
      // A client with a REAL gcTime, deliberately, and the mechanism is worth stating precisely
      // because the obvious reading is wrong. It is NOT the table unmounting: `useQueryResults`
      // and `useColumnWidths` both live at the workspace level, above that boundary, exactly so
      // they survive. What happens is that switching tabs sends `displayExecutionId` to null, so
      // the results query KEY changes and `q-1` is left with no observer — which the harness's
      // `gcTime: 0` evicts instantly. Coming back re-fetches cold, `columns.length` is 0 for a
      // beat, and `useColumnWidths` re-seeds to defaults.
      //
      // Production sets no `gcTime` (lib/queryClient.ts), so TanStack's 5-minute default keeps
      // the pages cached and the dip never happens. Asserting the reset here would have pinned
      // the test client's behaviour as if it were the feature's. (The persistence is bounded by
      // that cache rather than by the session — see the delivery doc.)
      const {user, container} = renderWorkspace(undefined, {
        queryClient: new QueryClient({defaultOptions: {queries: {retry: false, staleTime: 0}}})
      });
      await runOnce(user);
      await screen.findByText('us-east');

      // Read through the <col> element, and this is the FR-009 exception rather than laziness:
      // the width has no accessible contract to assert — the separator exposes no
      // `aria-valuenow`, and the header's own style is not where the width lands.
      const regionWidth = () => (container.querySelectorAll('colgroup col')[1] as HTMLElement).style.width;
      const before = regionWidth();

      // The keyboard path is the accessible one and the only one jsdom can drive honestly:
      // ColumnResizeHandle is a role="separator" that nudges by COLUMN_RESIZE_STEP_PX.
      const handle = screen.getByRole('separator', {name: 'Resize column region'});
      handle.focus();
      await user.keyboard('{ArrowRight}{ArrowRight}');
      const widened = regionWidth();
      expect(widened).not.toBe(before);

      await user.click(screen.getByRole('tab', {name: /Query 2/}));
      await user.click(screen.getByRole('tab', {name: /Query 1/}));

      expect(regionWidth()).toBe(widened);
    });

    it('applies an editor layout preset and keeps it for the session', async () => {
      seedSingle('SELECT 1');
      const {user, unmount} = renderWorkspace();
      await screen.findByRole('button', {name: 'sales_2026'});

      // The precondition, so the assertion after the click cannot pass by having started true.
      expect(screen.getByRole('button', {name: /Results layout/})).toHaveAttribute('aria-pressed', 'false');

      await user.click(screen.getByRole('button', {name: /Results layout/}));
      expect(screen.getByRole('button', {name: /Results layout/})).toHaveAttribute('aria-pressed', 'true');
      // NOTE: only the SELECTION and its persistence are asserted. "Applies" is unobservable in
      // jsdom — the pane container measures 0, so `clampEditorHeight` returns MIN_EDITOR_HEIGHT
      // for every preset and the three would render identically. Recorded rather than faked.

      // SPEC-079 persists per user for the session, so a remount must not silently revert —
      // the failure a hook test cannot see is the workspace not reading the stored value back.
      unmount();
      renderWorkspace();
      expect(await screen.findByRole('button', {name: /Results layout/})).toHaveAttribute('aria-pressed', 'true');
    });
  });
});

// ─── from QueryWorkspace.a11y.test.tsx ───

describe('QueryWorkspace.a11y', () => {
  // Integration a11y (react.md §21): render the REAL workspace — real SchemaBrowser
  // over the mocked glue boundary, the real tab strip/toolbar/results shell — and
  // check it under axe. Only the AWS service boundary + the heavy Monaco editor are
  // mocked. The QueryClient is pre-seeded so the schema rail shows real tables at
  // axe time rather than a transient loading state.

  // NOTE: the env stubs this section needs are set once at the top of the file. A
  // `vi.stubEnv` inside a describe body runs at COLLECTION time and applies file-wide,
  // so a second copy here would not be scoped to this section anyway.

  /**
   * The real workspace inside seeded providers (schema tables warm in the cache).
   *
   * Bespoke tree, kept deliberately (SPEC-154 FR-007): `expectNoA11yViolations` takes a
   * COMPOSED ELEMENT and renders it itself, so there is no `renderWithProviders` result
   * to hand it. The QueryClient is still the harness's, so retry behaviour cannot drift.
   */
  function workspace(): ReactElement {
    const client = createTestQueryClient();
    client.setQueryData(connectionKeys.list('alice'), {version: 1, connections: []});
    client.setQueryData(catalogKeys.schema('alice'), {
      database: {name: 'alice'},
      tables: [{name: 'sales_2026', location: 's3://b/alice/sales/', columns: [{name: 'region', type: 'string'}]}]
    });
    client.setQueryData(queryKeys.history('alice'), {version: 1, entries: []});
    client.setQueryData(savedQueryKeys.list('personal'), {
      pages: [{queries: [], isTruncated: false}],
      pageParams: [undefined]
    });
    return (
      <AuthContext.Provider value={authValue()}>
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <ToastProvider>
              <QueryWorkspace />
            </ToastProvider>
          </MemoryRouter>
        </QueryClientProvider>
      </AuthContext.Provider>
    );
  }

  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    // The suite-wide mocks above are bare `vi.fn()`; these cases need the boundary to
    // resolve so axe sees a populated workspace rather than a loading state.
    vi.mocked(getDatabase).mockResolvedValue({success: true, data: {name: 'alice'}});
    vi.mocked(listTables).mockResolvedValue({success: true, data: []});
    vi.mocked(getQueryHistory).mockResolvedValue({success: true, data: {version: 1, entries: []}});
    vi.mocked(listSavedQueries).mockResolvedValue({
      success: true,
      data: {queries: [], isTruncated: false}
    });
    vi.mocked(ensureSavedQueriesFolder).mockResolvedValue({success: true, data: undefined});
    vi.mocked(readSharedConnectionsCache).mockResolvedValue({
      success: true,
      data: {version: 1, connections: []}
    });
  });

  describe('QueryWorkspace accessibility (SPEC-045 FR-003)', () => {
    it('has no axe violations with the schema rail populated', async () => {
      await expectNoA11yViolations(workspace(), ROUTE_AXE_OPTIONS);
    });
  });
});
