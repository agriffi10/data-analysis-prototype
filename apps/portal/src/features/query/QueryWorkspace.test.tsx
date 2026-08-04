import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {screen, within, waitFor} from '@testing-library/react';
import {useLocation} from 'react-router-dom';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {NavRailProvider} from '../../components/NavRailProvider';
import {useNavRailContent} from '../../components/navRailContext';

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
vi.mock('./SqlEditor', async () => {
  const {forwardRef, useImperativeHandle, useRef} = await import('react');
  return {
    SqlEditor: forwardRef<import('./SqlEditor').SqlEditorHandle, {value: string; onChange: (v: string) => void}>(
      function MockSqlEditor({value, onChange}, ref) {
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
          <textarea
            ref={taRef}
            aria-label="SQL editor"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        );
      }
    )
  };
});

// ── AWS service boundary (the only real seam) ────────────────────────────────
vi.mock('./query.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./query.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getTableDdl: vi.fn(),
  runStatementToCompletion: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn()
}));
vi.mock('./glue.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./glue.service')>()),
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));
vi.mock('./queryHistory.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./queryHistory.service')>()),
  getQueryHistory: vi.fn(),
  appendQueryHistory: vi.fn(),
  updateQueryHistoryEntry: vi.fn()
}));
vi.mock('./savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./savedQueries.service')>()),
  getSavedQueries: vi.fn(),
  upsertSavedQuery: vi.fn(),
  removeSavedQuery: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
// copyObject = Save-results copy; listFiles = the SaveResultsDialog's real
// DestinationPicker folder listing.
vi.mock('../file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../file-browser/fileBrowser.service')>()),
  copyObject: vi.fn(),
  listFiles: vi.fn()
}));
vi.mock('../table-share/tableShare.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-share/tableShare.service')>()),
  enqueueTableShare: vi.fn()
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}}),
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'id-token'})
}));

import {
  runQuery,
  stopQuery,
  getTableDdl,
  runStatementToCompletion,
  getQueryStatus,
  getQueryResults
} from './query.service';
import {getDatabase, listTables} from './glue.service';
import {getQueryHistory, appendQueryHistory, updateQueryHistoryEntry} from './queryHistory.service';
import {getSavedQueries, upsertSavedQuery, removeSavedQuery} from './savedQueries.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {copyObject, listFiles} from '../file-browser/fileBrowser.service';
import {QueryWorkspace} from './QueryWorkspace';
import {QUERY_DRAFT_STORAGE_PREFIX, QUERY_TABS_STORAGE_PREFIX} from './query.constants';
import type {QueryTabsState, QueryState} from './query.types';

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
const mockGetSaved = vi.mocked(getSavedQueries);
const mockUpsert = vi.mocked(upsertSavedQuery);
const mockRemove = vi.mocked(removeSavedQuery);
const mockReadCache = vi.mocked(readSharedConnectionsCache);
const mockCopyObject = vi.mocked(copyObject);
const mockListFiles = vi.mocked(listFiles);

// SaveResultsDialog / runQuery outputLocation read these at render/module time.
vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bucket');
vi.stubEnv('VITE_ATHENA_WORKGROUP', 'primary');

const ok = <T,>(data: T) => ({success: true as const, data});
const fail = (message: string, code?: string) => ({success: false as const, error: {message, ...(code ? {code} : {})}});

// ── Builders ────────────────────────────────────────────────────────────────
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

const rowsPage = {columns: [{name: 'region', type: 'string'}], rows: [['us-east'], ['eu-west']], nextToken: undefined};

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

function renderWorkspace() {
  return renderWithProviders(
    <>
      <QueryWorkspace />
      <LocationProbe />
    </>,
    {auth: authenticated('alice')}
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
  mockGetSaved.mockResolvedValue(ok({version: 1, queries: []}));
  mockAppend.mockResolvedValue(ok({version: 1, entries: []}));
  mockUpdate.mockResolvedValue(ok({version: 1, entries: []}));
  mockUpsert.mockResolvedValue(ok({version: 1, queries: []}));
  mockRemove.mockResolvedValue(ok({version: 1, queries: []}));
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
    mockRunQuery.mockResolvedValue(fail('COLUMN_NOT_FOUND: amont', 'InvalidRequest'));
    const {user} = renderWorkspace();
    await screen.findByLabelText('SQL editor');

    await user.click(screen.getByRole('button', {name: 'Run statement'}));

    // SPEC-106: friendly, mapped guidance — never the raw Athena engine text.
    expect(await screen.findByText(/A column in your query wasn’t found/)).toBeInTheDocument();
    expect(screen.queryByText(/COLUMN_NOT_FOUND/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Run statement'})).toBeInTheDocument();
  });

  it('disables Run/Clear/Save/Create view when the buffer is empty', async () => {
    seedSingle(''); // an empty tab (a fresh tab is seeded with boilerplate)
    renderWorkspace();
    await screen.findByLabelText('SQL editor');
    expect(screen.getByRole('button', {name: 'Run statement'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Clear query'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Save query'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Create view'})).toBeDisabled();
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

  it('migrates a SPEC-040 draft into tab 1 on first load (back-compat)', async () => {
    sessionStorage.setItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`, 'SELECT migrated;');
    renderWorkspace();

    expect(await screen.findByLabelText('SQL editor')).toHaveValue('SELECT migrated;');
    expect(sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`)).toBeNull();
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

  it('Clear cancel leaves the tab untouched; confirm empties it and disables Run', async () => {
    seedSingle('SELECT * FROM persisted;');
    const {user} = renderWorkspace();
    await screen.findByLabelText('SQL editor');

    await user.click(screen.getByRole('button', {name: 'Clear query'}));
    await user.click(
      within(screen.getByRole('alertdialog', {name: /confirm clear query/i})).getByRole('button', {name: 'Cancel'})
    );
    expect(editor()).toHaveValue('SELECT * FROM persisted;');

    await user.click(screen.getByRole('button', {name: 'Clear query'}));
    await user.click(
      within(screen.getByRole('alertdialog', {name: /confirm clear query/i})).getByRole('button', {name: 'Clear'})
    );
    expect(editor()).toHaveValue('');
    expect(screen.getByRole('button', {name: 'Run statement'})).toBeDisabled();
  });

  it('finalizes a backgrounded running tab while another tab is active', async () => {
    seedSingle('SELECT 1');
    const {user} = renderWorkspace();
    await screen.findByLabelText('SQL editor');

    await user.click(screen.getByRole('button', {name: 'Run statement'}));
    expect(await screen.findByText('us-east')).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'New query tab'}));
    expect(screen.getByText('Run a query to see results.')).toBeInTheDocument();
    // Query 1's execution finalized its history in the background.
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith('alice', 'q-1', expect.objectContaining({status: 'SUCCEEDED'}))
    );

    await user.click(screen.getByRole('tab', {name: /Query 1/}));
    expect(screen.getByText('us-east')).toBeInTheDocument();
  });

  // --- saved queries ---

  it('saves a new query: prompts, upserts, links + relabels the active tab', async () => {
    seedSingle('SELECT r;');
    const {user} = renderWorkspace();
    await screen.findByLabelText('SQL editor');

    await user.click(screen.getByRole('button', {name: 'Save query'}));
    const dialog = screen.getByRole('dialog', {name: 'Save query'});
    await user.type(within(dialog).getByLabelText('Name'), 'My report');
    await user.click(within(dialog).getByRole('button', {name: 'Save'}));

    expect(mockUpsert).toHaveBeenCalledWith('alice', expect.objectContaining({name: 'My report', sql: 'SELECT r;'}));
    expect(await screen.findByRole('tab', {name: /My report/})).toBeInTheDocument();
  });

  it('shows a dirty marker on a linked tab whose SQL diverged from the saved query', async () => {
    seedTabs({
      version: 1,
      tabs: [{id: 't1', label: 'Revenue', sql: 'SELECT edited;', savedQueryId: 'sq1'}],
      activeTabId: 't1',
      nextQueryNumber: 2
    });
    mockGetSaved.mockResolvedValue(
      ok({
        version: 1,
        queries: [
          {
            id: 'sq1',
            name: 'Revenue',
            sql: 'SELECT original;',
            database: 'alice',
            createdAt: '2026-06-01T00:00:00.000Z',
            updatedAt: '2026-06-01T00:00:00.000Z'
          }
        ]
      })
    );
    renderWorkspace();
    expect(await screen.findByLabelText('Unsaved changes')).toBeInTheDocument();
  });

  it('opens a saved query into a new linked tab and records its name in history on run', async () => {
    mockGetSaved.mockResolvedValue(
      ok({
        version: 1,
        queries: [
          {
            id: 'sq1',
            name: 'Revenue',
            sql: 'SELECT 1;',
            database: 'alice',
            createdAt: '2026-06-01T00:00:00.000Z',
            updatedAt: '2026-06-01T00:00:00.000Z'
          }
        ]
      })
    );
    const {user} = renderWorkspace();
    await screen.findByLabelText('SQL editor');

    await user.click(screen.getByRole('button', {name: 'Saved queries'}));
    await user.click(await screen.findByRole('button', {name: /open saved query/i}));
    expect(screen.getByRole('tab', {name: /Revenue/})).toBeInTheDocument();
    expect(editor()).toHaveValue('SELECT 1;');

    await user.click(screen.getByRole('button', {name: 'Run statement'}));
    await screen.findByText('Succeeded');
    expect(mockAppend).toHaveBeenCalledWith(
      'alice',
      expect.objectContaining({savedQueryId: 'sq1', savedQueryName: 'Revenue'})
    );
  });

  it('deletes a saved query (confirm) and calls remove', async () => {
    mockGetSaved.mockResolvedValue(
      ok({
        version: 1,
        queries: [
          {
            id: 'sq1',
            name: 'Revenue',
            sql: 'SELECT r;',
            database: 'alice',
            createdAt: '2026-06-01T00:00:00.000Z',
            updatedAt: '2026-06-01T00:00:00.000Z'
          }
        ]
      })
    );
    const {user} = renderWorkspace();
    await screen.findByLabelText('SQL editor');

    await user.click(screen.getByRole('button', {name: 'Saved queries'}));
    await user.click(await screen.findByRole('button', {name: /delete saved query/i}));
    await user.click(
      within(screen.getByRole('alertdialog', {name: /confirm delete saved query/i})).getByRole('button', {
        name: 'Delete'
      })
    );
    expect(mockRemove).toHaveBeenCalledWith('alice', 'sq1');
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

  it('View DDL opens non-run DDL tabs for a table (SHOW CREATE TABLE) and a view (isView passthrough)', async () => {
    mockGetTableDdl.mockResolvedValue(ok('CREATE EXTERNAL TABLE sales_2026 (...)'));
    const {user} = renderWorkspace();

    await openTableMenu(user, 'sales_2026');
    await user.click(await screen.findByRole('menuitem', {name: 'View DDL'}));
    expect(await screen.findByRole('tab', {name: /DDL: sales_2026/})).toBeInTheDocument();
    expect(editor()).toHaveValue('CREATE EXTERNAL TABLE sales_2026 (...)');
    expect(mockGetTableDdl).toHaveBeenCalledWith(
      expect.objectContaining({database: 'alice', table: 'sales_2026', isView: false})
    );
    expect(mockRunQuery).not.toHaveBeenCalled(); // a DDL fetch is not a run

    mockGetTableDdl.mockResolvedValue(ok('CREATE VIEW revenue_view ...'));
    await openTableMenu(user, 'revenue_view');
    await user.click(await screen.findByRole('menuitem', {name: 'View DDL'}));
    expect(mockGetTableDdl).toHaveBeenLastCalledWith(expect.objectContaining({table: 'revenue_view', isView: true}));
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
    expect(mockRunToCompletion).toHaveBeenCalledWith(expect.objectContaining({sql: 'DROP TABLE alice.sales_2026'}));
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

  it('Drop on a view confirms and runs DROP VIEW', async () => {
    mockRunToCompletion.mockResolvedValue(ok(succeeded('q-dropview')));
    const {user} = renderWorkspace();

    await openTableMenu(user, 'revenue_view');
    await user.click(await screen.findByRole('menuitem', {name: 'Drop view'}));
    await user.click(
      within(screen.getByRole('alertdialog', {name: /confirm drop view/i})).getByRole('button', {name: 'Drop view'})
    );

    expect(await screen.findByText('Dropped revenue_view')).toBeInTheDocument();
    expect(mockRunToCompletion).toHaveBeenCalledWith(expect.objectContaining({sql: 'DROP VIEW alice.revenue_view'}));
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
        sql: 'CREATE OR REPLACE VIEW alice.region_view AS SELECT region FROM alice.sales',
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

  it('Stop mid-batch halts the remainder even when the in-flight statement succeeds (FR-002)', async () => {
    queueRuns('q-1', 'q-2');
    statusMap['q-1'] = {state: 'RUNNING'};
    seedScript('SELECT 1;\nSELECT 2;');
    const {user} = renderWorkspace();
    await screen.findByLabelText('SQL editor');

    await runScriptSingle(user);
    const stop = await screen.findByRole('button', {name: /Stop/});
    statusMap['q-1'] = {state: 'SUCCEEDED'}; // outruns the cancel
    await user.click(stop);

    expect(mockStopQuery).toHaveBeenCalledWith('q-1');
    await screen.findByText('Succeeded', undefined, {timeout: 3000});
    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Script finished/)).not.toBeInTheDocument();
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

  it('shows batch progress in the status bar while running (FR-004)', async () => {
    queueRuns('q-1', 'q-2', 'q-3');
    statusMap['q-2'] = {state: 'RUNNING'};
    seedScript();
    const {user} = renderWorkspace();
    await screen.findByLabelText('SQL editor');

    await runScriptSingle(user);
    await screen.findByRole('button', {name: /Stop/});
    expect(await screen.findByText(/Statement 2 of 3/, undefined, {timeout: 3000})).toBeInTheDocument();
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

// ── SPEC-100: responsive workspace ──────────────────────────────────────────
describe('QueryWorkspace responsive (SPEC-100)', () => {
  const savedFixture = (id: string, name: string) => ({
    id,
    name,
    sql: `SELECT region FROM alice.${name.toLowerCase()}`,
    database: 'alice',
    createdAt: '2026-07-01T10:00:00.000Z',
    updatedAt: '2026-07-01T10:00:00.000Z'
  });

  /** Renders inside a NavRailProvider so the mobile drawer's contextual slot is observable. */
  function renderMobileWorkspace() {
    window.innerWidth = 390;
    return renderWithProviders(
      <NavRailProvider>
        <QueryWorkspace />
        <NavRailProbe />
      </NavRailProvider>,
      {auth: authenticated('alice')}
    );
  }

  it('pares the workspace to a browse-first surface below tablet — no editor, toolbar or tab strip', async () => {
    mockGetSaved.mockResolvedValue(
      ok({
        version: 1,
        queries: [
          {
            id: 's1',
            name: 'Revenue',
            sql: 'SELECT 1',
            database: 'alice',
            createdAt: '2026-07-01T10:00:00.000Z',
            updatedAt: '2026-07-01T10:00:00.000Z'
          }
        ]
      })
    );
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
    mockGetSaved.mockResolvedValue(
      ok({
        version: 1,
        queries: [
          {
            id: 's1',
            name: 'Revenue',
            sql: 'SELECT region FROM alice.sales',
            database: 'alice',
            createdAt: '2026-07-01T10:00:00.000Z',
            updatedAt: '2026-07-01T10:00:00.000Z'
          }
        ]
      })
    );
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

  it('drops the toolbar labels in the tablet band while keeping the accessible names', () => {
    window.innerWidth = 1024; // tablet band
    renderWorkspace();
    // Icon-only is a CSS concern jsdom can't compute; assert the label carries the
    // desktop-only visibility utility and the button keeps its accessible name.
    expect(screen.getByText('Clear')).toHaveClass('hidden', 'desktop:inline');
    expect(screen.getByRole('button', {name: 'Clear query'})).toBeInTheDocument();
    expect(screen.getByText('Run Statement')).toHaveClass('hidden', 'desktop:inline');
    expect(screen.getByRole('button', {name: 'Run statement'})).toBeInTheDocument();
  });

  it('never shows one query’s results under another query’s name', async () => {
    mockGetSaved.mockResolvedValue(
      ok({version: 1, queries: [savedFixture('s1', 'Revenue'), savedFixture('s2', 'Costs')]})
    );
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

  it('leaves the editor’s draft untouched when a card is run', async () => {
    seedSingle('SELECT my_unsaved_draft');
    mockGetSaved.mockResolvedValue(ok({version: 1, queries: [savedFixture('s1', 'Revenue')]}));
    const {user} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));
    await waitFor(() => expect(mockRunQuery).toHaveBeenCalled());

    // The draft is persisted state a wider screen owns — running here must not
    // overwrite it (the run carries its own statements).
    const persisted = JSON.parse(sessionStorage.getItem(`${QUERY_TABS_STORAGE_PREFIX}alice`) as string);
    expect(persisted.tabs[0].sql).toBe('SELECT my_unsaved_draft');
  });

  it('stops claiming a query is running once its failure is dismissed', async () => {
    mockGetSaved.mockResolvedValue(ok({version: 1, queries: [savedFixture('s1', 'Revenue')]}));
    mockRunQuery.mockResolvedValueOnce(fail('Rate exceeded', 'ThrottlingException'));
    const {user} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));
    await user.click(await screen.findByRole('button', {name: 'Dismiss'}));

    // The submit never reached Athena: with the banner gone there is nothing to
    // report, and nothing may imply the query is still in flight.
    expect(screen.queryByText('Query failed.')).not.toBeInTheDocument();
    expect(screen.queryByText('Running your query…')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Run'})).toBeEnabled();
  });

  it('holds an honest in-flight state between the tap and the run starting', async () => {
    mockGetSaved.mockResolvedValue(ok({version: 1, queries: [savedFixture('s1', 'Revenue')]}));
    let startRun: (v: {success: true; data: {queryExecutionId: string}}) => void = () => {};
    mockRunQuery.mockReturnValueOnce(new Promise((resolve) => (startRun = resolve)));
    const {user} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));

    // The run isn't installed on the tab yet — the view must say so, and must not
    // invite a second tap while it does.
    expect(await screen.findByText('Running your query…')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Run'})).toBeDisabled();

    startRun(ok({queryExecutionId: 'q-1'}));
    expect(await screen.findByLabelText('Row 1')).toBeInTheDocument();
  });

  it('reports a submit that throws instead of waiting on it forever', async () => {
    mockGetSaved.mockResolvedValue(ok({version: 1, queries: [savedFixture('s1', 'Revenue')]}));
    // Services don't throw by contract; if one does, the outcome still has to settle.
    mockRunQuery.mockRejectedValueOnce(new Error('socket hang up'));
    const {user} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));

    expect(await screen.findByText('Query failed.')).toBeInTheDocument();
    expect(screen.queryByText('Running your query…')).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Run'})).toBeEnabled();
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
    mockGetSaved.mockResolvedValue(ok({version: 1, queries: [savedFixture('s1', 'Revenue')]}));
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

  it('does not carry a failed mobile submit onto the editor shell — even when it fails after the crossing', async () => {
    seedSingle('SELECT my_unsaved_draft');
    mockGetSaved.mockResolvedValue(ok({version: 1, queries: [savedFixture('s1', 'Revenue')]}));
    let failRun: (v: {success: false; error: {message: string; code?: string}}) => void = () => {};
    mockRunQuery.mockReturnValueOnce(new Promise((resolve) => (failRun = resolve)));
    const {user, rerender} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));
    expect(await screen.findByText('Running your query…')).toBeInTheDocument();

    // Cross to the editor while the submit is still in flight, then let it fail:
    // it installs no run, so nothing marks it as the phone's by the usual route.
    window.innerWidth = 1400;
    rerender(
      <NavRailProvider>
        <QueryWorkspace />
        <NavRailProbe />
      </NavRailProvider>
    );
    failRun(fail('Rate exceeded', 'ThrottlingException'));

    expect(await screen.findByLabelText('SQL editor')).toHaveValue('SELECT my_unsaved_draft');
    await waitFor(() => expect(mockRunQuery).toHaveBeenCalled());
    expect(screen.queryByText('Query failed.')).not.toBeInTheDocument();
  });

  it('returns to the list the run started from', async () => {
    mockGetHistory.mockResolvedValue(
      ok({
        version: 1,
        entries: [
          {
            queryExecutionId: 'q-old',
            sql: 'SELECT 1',
            database: 'alice',
            submittedAt: '2026-07-01T10:00:00.000Z',
            status: 'SUCCEEDED' as QueryState
          }
        ]
      })
    );
    const {user} = renderMobileWorkspace();

    await user.click(screen.getByRole('button', {name: 'History'}));
    await user.click(await screen.findByRole('button', {name: 'Run this query'}));
    await user.click(await screen.findByRole('button', {name: 'Back to queries'}));

    expect(await screen.findByRole('button', {name: 'History'})).toHaveAttribute('aria-pressed', 'true');
  });
});
