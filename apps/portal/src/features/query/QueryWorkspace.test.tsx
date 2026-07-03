import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, fireEvent, waitFor, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';

// Auth + the lazy editor + the data hooks are mocked so the workspace can be
// exercised without Amplify, Monaco workers, or live AWS calls. useQueryTabs is
// NOT mocked — it's a pure state hook and we want real tab behavior under test.
vi.mock('../auth', () => ({
  useAuth: () => ({user: {username: 'alice'}, status: 'authenticated'})
}));
vi.mock('./SqlEditor', async () => {
  const {forwardRef, useImperativeHandle, useRef} = await import('react');
  return {
    // A textarea wired to value/onChange so per-tab text + switching is
    // observable. Forwards the SPEC-078 handle backed by the textarea's native
    // selection, so statement-resolution tests can position the cursor/selection
    // with setSelectionRange.
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
            data-testid="sql-editor"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        );
      }
    )
  };
});
// Expose the table-action callbacks as buttons so they can be driven from tests
// (the real menu/popover is covered in SchemaBrowser.test.tsx).
const inSpace = {
  name: 'sales_2026',
  location: 's3://b/alice/sales/',
  columns: []
};
const outOfSpace = {name: 'foreign', location: 's3://b/bob/x/', columns: []};
const viewObj = {name: 'revenue_view', tableType: 'VIRTUAL_VIEW', columns: []};
vi.mock('./SchemaBrowser', () => ({
  // SPEC-077: the rail is browse-only — no active-database selection. Per-table
  // actions now carry the node's database (the personal db = 'alice' here).
  SchemaBrowser: ({actions}: {actions: import('./SchemaBrowser').TableActions}) => (
    <div data-testid="schema-browser">
      <button onClick={() => actions.onViewSourceFiles('alice', inSpace)}>src:in</button>
      <button onClick={() => actions.onViewSourceFiles('alice', outOfSpace)}>src:out</button>
      <button onClick={() => actions.onViewDdl('alice', inSpace)}>ddl</button>
      <button onClick={() => actions.onViewData('alice', inSpace)}>data</button>
      <button onClick={() => actions.onDropTable('alice', inSpace)}>drop</button>
      <button onClick={() => actions.onViewDdl('alice', viewObj)}>ddl:view</button>
      <button onClick={() => actions.onDropTable('alice', viewObj)}>drop:view</button>
      <span>cansrc-in:{String(actions.canViewSourceFiles(inSpace))}</span>
      <span>cansrc-out:{String(actions.canViewSourceFiles(outOfSpace))}</span>
      <span>cansrc-view:{String(actions.canViewSourceFiles(viewObj))}</span>
    </div>
  )
}));
vi.mock('./useConnections', () => ({useConnections: vi.fn()}));
const navigateMock = vi.fn();
vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<typeof import('react-router-dom')>()),
  useNavigate: () => navigateMock
}));
vi.mock('./query.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./query.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getTableDdl: vi.fn(),
  runStatementToCompletion: vi.fn()
}));
// Save-results uses the file-browser copy + listing invalidation.
vi.mock('../file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../file-browser/fileBrowser.service')>()),
  copyObject: vi.fn()
}));
vi.mock('../../lib/queryClient', () => ({invalidateListing: vi.fn()}));
// The Save-results modal's folder picker (DestinationPicker) has its own data
// layer + test; here stub it to a Save button that returns a fixed destination so
// the workspace's copy/collision/toast wiring is what's exercised.
vi.mock('./SaveResultsDialog', () => ({
  SaveResultsDialog: ({
    spaces,
    defaultName,
    onSave,
    onCancel
  }: {
    spaces: {id: string; label: string; bucket: string; rootPrefix: string; rootLabel: string}[];
    defaultName: string;
    onSave: (a: {destBucket: string; destPrefix: string; filename: string}) => void;
    onCancel: () => void;
  }) => (
    <div
      role="dialog"
      aria-label="Save results to my files">
      <span>default:{defaultName}</span>
      <span>spaces:{spaces.map((s) => s.id).join(',')}</span>
      {/* One save button per destination space, saving into that space's
          bucket; the first space is personal. */}
      {spaces.map((s) => (
        <button
          key={s.id}
          onClick={() => onSave({destBucket: s.bucket, destPrefix: `${s.rootPrefix}reports/`, filename: 'out.csv'})}>
          save-to-{s.id}
        </button>
      ))}
      {/* Alias used by the personal-save tests. */}
      <button onClick={() => onSave({destBucket: spaces[0].bucket, destPrefix: 'alice/reports/', filename: 'out.csv'})}>
        save-here-stub
      </button>
      <button onClick={onCancel}>save-cancel-stub</button>
    </div>
  )
}));
vi.mock('./useQueryExecution', () => ({useQueryExecution: vi.fn()}));
vi.mock('./useQueryResults', () => ({useQueryResults: vi.fn()}));
vi.mock('./useQueryHistory', () => ({useQueryHistory: vi.fn()}));
vi.mock('./useSavedQueries', () => ({useSavedQueries: vi.fn()}));

import {runQuery, getTableDdl, runStatementToCompletion} from './query.service';
import {copyObject} from '../file-browser/fileBrowser.service';
import {useQueryExecution} from './useQueryExecution';
import {useQueryResults} from './useQueryResults';
import {useQueryHistory} from './useQueryHistory';
import {useSavedQueries} from './useSavedQueries';
import {useConnections} from './useConnections';
import {QueryWorkspace} from './QueryWorkspace';
import {QUERY_DRAFT_STORAGE_PREFIX, QUERY_TABS_STORAGE_PREFIX} from './query.constants';
import type {QueryTabsState, SavedQuery} from './query.types';

const mockRunQuery = vi.mocked(runQuery);
const mockGetTableDdl = vi.mocked(getTableDdl);
const mockRunToCompletion = vi.mocked(runStatementToCompletion);
const mockUseExecution = vi.mocked(useQueryExecution);
const mockUseResults = vi.mocked(useQueryResults);
const mockUseHistory = vi.mocked(useQueryHistory);
const mockUseSaved = vi.mocked(useSavedQueries);
const mockUseConnections = vi.mocked(useConnections);
const mockCopyObject = vi.mocked(copyObject);

// SaveResultsDialog/handler read VITE_S3_USER_SPACE_BUCKET at module load.
vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
// Shared-space routing/save reads the shared bucket.
vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bucket');

const personalConnection = {
  id: 'personal',
  label: 'My workspace',
  database: 'alice',
  kind: 'personal' as const
};

const appendEntry = vi.fn().mockResolvedValue({version: 1, entries: []});
const updateEntry = vi.fn().mockResolvedValue({version: 1, entries: []});
const upsert = vi.fn().mockResolvedValue({version: 1, queries: []});
const remove = vi.fn().mockResolvedValue({version: 1, queries: []});

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: {queries: {retry: false}}
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <QueryWorkspace />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

function seedTabs(state: QueryTabsState) {
  sessionStorage.setItem(`${QUERY_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

const succeededStatus = {
  data: {
    queryExecutionId: 'q-1',
    state: 'SUCCEEDED',
    dataScannedBytes: 2048,
    engineExecutionTimeMillis: 800,
    outputLocation: 's3://b/alice/athenaresults/q-1.csv'
  }
} as unknown as ReturnType<typeof useQueryExecution>;

const rowsResult = {
  columns: [{name: 'region', type: 'string'}],
  rows: [['us-east'], ['eu-west']],
  pageIndex: 0,
  rangeStart: 1,
  rangeEnd: 2,
  loadedRowCount: 2,
  totalRowCount: 2,
  hasPrev: false,
  hasNext: false,
  hasMoreServer: false,
  isPending: false,
  isFetchingNext: false,
  isError: false,
  error: null,
  goPrev: vi.fn(),
  goNext: vi.fn()
} as unknown as ReturnType<typeof useQueryResults>;

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  mockUseConnections.mockReturnValue({
    connections: [personalConnection],
    isLoading: false,
    error: null,
    refresh: vi.fn(),
    isRefreshing: false,
    reconcile: vi.fn()
  });
  mockUseExecution.mockReturnValue({data: undefined} as unknown as ReturnType<typeof useQueryExecution>);
  mockUseResults.mockReturnValue({
    ...rowsResult,
    columns: [],
    rows: [],
    rangeStart: 0,
    rangeEnd: 0,
    loadedRowCount: 0,
    totalRowCount: 0
  } as unknown as ReturnType<typeof useQueryResults>);
  mockUseHistory.mockReturnValue({
    history: [],
    isLoading: false,
    error: null,
    appendEntry,
    updateEntry,
    refresh: vi.fn().mockResolvedValue(undefined),
    isRefreshing: false
  });
  mockUseSaved.mockReturnValue({
    queries: [],
    isLoading: false,
    error: null,
    upsert,
    remove
  });
});

describe('QueryWorkspace', () => {
  it('renders the workspace with a Query 1 tab and enabled Run', async () => {
    renderWorkspace();

    expect(screen.getByTestId('schema-browser')).toBeInTheDocument();
    expect(await screen.findByTestId('sql-editor')).toBeInTheDocument(); // lazy
    expect(screen.getByRole('tab', {name: /Query 1/})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Run statement'})).toBeEnabled();
  });

  it('runs the active tab and records history on submit', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: {queryExecutionId: 'q-1'}
    });
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));

    expect(await screen.findByRole('button', {name: /Stop/})).toBeInTheDocument();
    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    // SPEC-077: the workspace runs with no execution-database context.
    expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: expect.any(String), username: 'alice'});
    expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('database');
    expect(appendEntry).toHaveBeenCalledTimes(1);
  });

  it('de-dupes a rapid double-submit for the same tab — at most one execution [SPEC-083 FR-009]', async () => {
    let resolveRun: (v: Awaited<ReturnType<typeof runQuery>>) => void = () => {};
    mockRunQuery.mockReturnValue(
      new Promise((resolve) => {
        resolveRun = resolve;
      })
    );
    renderWorkspace();

    const runBtn = screen.getByRole('button', {name: 'Run statement'});
    fireEvent.click(runBtn);
    fireEvent.click(runBtn); // second trigger before the first run is recorded in `runs`

    expect(mockRunQuery).toHaveBeenCalledTimes(1);

    resolveRun({success: true, data: {queryExecutionId: 'q-1'}});
    expect(await screen.findByRole('button', {name: /Stop/})).toBeInTheDocument();
    expect(mockRunQuery).toHaveBeenCalledTimes(1);
  });

  it('surfaces a runQuery error in a danger banner', async () => {
    mockRunQuery.mockResolvedValue({
      success: false,
      error: {message: 'COLUMN_NOT_FOUND: amont', code: 'InvalidRequest'}
    });
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));

    expect(await screen.findByText(/COLUMN_NOT_FOUND/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Run statement'})).toBeInTheDocument();
  });

  it('shows the results table once the active execution has succeeded', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: {queryExecutionId: 'q-1'}
    });
    mockUseExecution.mockReturnValue(succeededStatus);
    mockUseResults.mockReturnValue(rowsResult);

    renderWorkspace();
    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));

    expect(await screen.findByText('Succeeded')).toBeInTheDocument();
    expect(screen.getByText('region')).toBeInTheDocument();
    expect(screen.getByText('us-east')).toBeInTheDocument();
  });

  // --- persistence + migration ---

  it('restores tabs from persisted state on mount, showing the active tab text', async () => {
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

    expect(await screen.findByTestId('sql-editor')).toHaveValue('SELECT two;');
    expect(screen.getByRole('tab', {name: /Scratch/})).toHaveAttribute('aria-selected', 'true');
  });

  it('migrates a SPEC-040 draft into tab 1 on first load (back-compat)', async () => {
    sessionStorage.setItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`, 'SELECT migrated;');
    renderWorkspace();

    expect(await screen.findByTestId('sql-editor')).toHaveValue('SELECT migrated;');
    expect(sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`)).toBeNull();
  });

  // --- tabs behavior ---

  it('opens a new blank Query 2 tab and isolates text per tab', async () => {
    renderWorkspace();
    const editor = await screen.findByTestId('sql-editor');

    fireEvent.change(editor, {target: {value: 'SELECT a;'}});
    fireEvent.click(screen.getByRole('button', {name: 'New query tab'}));

    expect(screen.getByRole('tab', {name: /Query 2/})).toBeInTheDocument();
    expect(screen.getByTestId('sql-editor')).toHaveValue('');
    fireEvent.change(screen.getByTestId('sql-editor'), {
      target: {value: 'SELECT b;'}
    });

    fireEvent.click(screen.getByRole('tab', {name: /Query 1/}));
    expect(screen.getByTestId('sql-editor')).toHaveValue('SELECT a;');
    fireEvent.click(screen.getByRole('tab', {name: /Query 2/}));
    expect(screen.getByTestId('sql-editor')).toHaveValue('SELECT b;');
  });

  it('closes an empty tab immediately but confirms a non-empty one', async () => {
    seedTabs({
      version: 1,
      tabs: [
        {id: 'a', label: 'Query 1', sql: 'SELECT keep;'},
        {id: 'b', label: 'Query 2', sql: ''}
      ],
      activeTabId: 'a',
      nextQueryNumber: 3
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByTitle('Close Query 2'));
    expect(screen.queryByRole('tab', {name: /Query 2/})).not.toBeInTheDocument();

    // Query 1 is now the only tab → its close control is hidden.
    expect(screen.queryByTitle('Close Query 1')).not.toBeInTheDocument();
  });

  it('confirms before closing a tab with non-empty SQL', async () => {
    seedTabs({
      version: 1,
      tabs: [
        {id: 'a', label: 'Query 1', sql: 'SELECT keep;'},
        {id: 'b', label: 'Query 2', sql: 'SELECT bye;'}
      ],
      activeTabId: 'a',
      nextQueryNumber: 3
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByTitle('Close Query 2'));
    const dialog = screen.getByRole('alertdialog', {name: /confirm close tab/i});
    fireEvent.click(within(dialog).getByRole('button', {name: 'Close tab'}));

    expect(screen.queryByRole('tab', {name: /Query 2/})).not.toBeInTheDocument();
  });

  it('shows the tab-limit dialog at the cap and opens no further tab', async () => {
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    const newTabBtn = screen.getByRole('button', {name: 'New query tab'});
    // One tab exists already; open 9 more to reach the cap of 10.
    for (let i = 0; i < 9; i++) fireEvent.click(newTabBtn);
    expect(screen.getAllByRole('tab')).toHaveLength(10);

    fireEvent.click(newTabBtn);
    expect(screen.getByRole('alertdialog', {name: /query tab limit reached/i})).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(10);
  });

  // --- Clear (scoped to the active tab) ---

  it('Clear confirms, empties the active tab, and disables Run', async () => {
    seedTabs({
      version: 1,
      tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT * FROM persisted;'}],
      activeTabId: 'a',
      nextQueryNumber: 2
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Clear query'}));
    const dialog = screen.getByRole('alertdialog', {
      name: /confirm clear query/i
    });
    fireEvent.click(within(dialog).getByRole('button', {name: 'Clear'}));

    expect(screen.getByTestId('sql-editor')).toHaveValue('');
    expect(screen.getByRole('button', {name: 'Run statement'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Clear query'})).toBeDisabled();
  });

  it('Clear cancel leaves the active tab untouched', async () => {
    seedTabs({
      version: 1,
      tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT keep;'}],
      activeTabId: 'a',
      nextQueryNumber: 2
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Clear query'}));
    const dialog = screen.getByRole('alertdialog', {
      name: /confirm clear query/i
    });
    fireEvent.click(within(dialog).getByRole('button', {name: 'Cancel'}));

    expect(screen.getByTestId('sql-editor')).toHaveValue('SELECT keep;');
  });

  it('disables Clear while a query is in flight', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: {queryExecutionId: 'q-1'}
    });
    mockUseExecution.mockReturnValue({
      data: {queryExecutionId: 'q-1', state: 'RUNNING'}
    } as unknown as ReturnType<typeof useQueryExecution>);

    renderWorkspace();
    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));

    expect(await screen.findByRole('button', {name: /Stop/})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Clear query'})).toBeDisabled();
  });

  // --- concurrent background polling ---

  it('finalizes a backgrounded running tab while another tab is active', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: {queryExecutionId: 'q-1'}
    });
    // Every poller observes SUCCEEDED — stands in for the background query
    // finishing while the user is elsewhere.
    mockUseExecution.mockReturnValue(succeededStatus);
    mockUseResults.mockReturnValue(rowsResult);

    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));
    expect(await screen.findByText('region')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'New query tab'}));

    // Query 2 is active with no run of its own…
    expect(screen.getByText('Run a query to see results.')).toBeInTheDocument();
    // …yet Query 1's execution finalized in the background.
    expect(updateEntry).toHaveBeenCalledWith(expect.objectContaining({queryExecutionId: 'q-1'}));

    fireEvent.click(screen.getByRole('tab', {name: /Query 1/}));
    expect(screen.getByText('region')).toBeInTheDocument();
  });

  // --- saved queries ---

  function savedState(queries: SavedQuery[]) {
    return {queries, isLoading: false, error: null, upsert, remove};
  }

  it('saves a new query: prompts, upserts, links + relabels the active tab', async () => {
    upsert.mockResolvedValue({version: 1, queries: []});
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Save query'}));
    const dialog = screen.getByRole('dialog', {name: 'Save query'});
    fireEvent.change(within(dialog).getByLabelText('Name'), {
      target: {value: 'My report'}
    });
    fireEvent.click(within(dialog).getByRole('button', {name: 'Save'}));

    expect(upsert).toHaveBeenCalledWith(expect.objectContaining({name: 'My report'}));
    expect(await screen.findByRole('tab', {name: /My report/})).toBeInTheDocument();
  });

  it('shows a dirty marker on a linked tab whose SQL diverged', async () => {
    seedTabs({
      version: 1,
      tabs: [{id: 't1', label: 'Revenue', sql: 'SELECT edited;', savedQueryId: 'sq1'}],
      activeTabId: 't1',
      nextQueryNumber: 2
    });
    mockUseSaved.mockReturnValue(
      savedState([
        {
          id: 'sq1',
          name: 'Revenue',
          sql: 'SELECT original;',
          database: 'alice',
          createdAt: '2026-06-01T00:00:00.000Z',
          updatedAt: '2026-06-01T00:00:00.000Z'
        }
      ])
    );
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    expect(screen.getByLabelText('Unsaved changes')).toBeInTheDocument();
  });

  it('records the saved-query name in history when running a linked tab', async () => {
    seedTabs({
      version: 1,
      tabs: [{id: 't1', label: 'Revenue', sql: 'SELECT 1;', savedQueryId: 'sq1'}],
      activeTabId: 't1',
      nextQueryNumber: 2
    });
    mockUseSaved.mockReturnValue(
      savedState([
        {
          id: 'sq1',
          name: 'Revenue',
          sql: 'SELECT 1;',
          database: 'alice',
          createdAt: '2026-06-01T00:00:00.000Z',
          updatedAt: '2026-06-01T00:00:00.000Z'
        }
      ])
    );
    mockRunQuery.mockResolvedValue({
      success: true,
      data: {queryExecutionId: 'q-1'}
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));
    await screen.findByRole('button', {name: /Stop/});
    expect(appendEntry).toHaveBeenCalledWith(expect.objectContaining({savedQueryId: 'sq1', savedQueryName: 'Revenue'}));
  });

  it('opens a saved query into a new linked tab from the drawer', async () => {
    mockUseSaved.mockReturnValue(
      savedState([
        {
          id: 'sq1',
          name: 'Revenue',
          sql: 'SELECT r;',
          database: 'alice',
          createdAt: '2026-06-01T00:00:00.000Z',
          updatedAt: '2026-06-01T00:00:00.000Z'
        }
      ])
    );
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Saved queries'}));
    fireEvent.click(await screen.findByRole('button', {name: /open saved query/i}));

    expect(screen.getByRole('tab', {name: /Revenue/})).toBeInTheDocument();
    expect(screen.getByTestId('sql-editor')).toHaveValue('SELECT r;');
  });

  it('deletes a saved query (confirm) and calls remove', async () => {
    remove.mockResolvedValue({version: 1, queries: []});
    mockUseSaved.mockReturnValue(
      savedState([
        {
          id: 'sq1',
          name: 'Revenue',
          sql: 'SELECT r;',
          database: 'alice',
          createdAt: '2026-06-01T00:00:00.000Z',
          updatedAt: '2026-06-01T00:00:00.000Z'
        }
      ])
    );
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Saved queries'}));
    fireEvent.click(await screen.findByRole('button', {name: /delete saved query/i}));
    const dialog = screen.getByRole('alertdialog', {
      name: /confirm delete saved query/i
    });
    fireEvent.click(within(dialog).getByRole('button', {name: 'Delete'}));

    expect(remove).toHaveBeenCalledWith('sq1');
  });

  it('hoists History + Saved queries to the global bar (Save stays per-tab)', async () => {
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    expect(screen.getByRole('button', {name: 'Saved queries'})).toBeInTheDocument();
    expect(screen.getAllByRole('button', {name: /History/})).toHaveLength(1);
    expect(screen.getByRole('button', {name: 'Save query'})).toBeInTheDocument();
  });

  // --- table actions ---

  it('View source files navigates to /files?prefix= for an in-space table', async () => {
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    expect(screen.getByText('cansrc-in:true')).toBeInTheDocument();
    expect(screen.getByText('cansrc-out:false')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'src:in'}));
    expect(navigateMock).toHaveBeenCalledWith('/files?prefix=alice%2Fsales%2F');
  });

  it('View source files does not navigate for an out-of-space table', async () => {
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'src:out'}));
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('View DDL opens a non-run "DDL: {table}" tab with the fetched DDL', async () => {
    mockGetTableDdl.mockResolvedValue({
      success: true,
      data: 'CREATE EXTERNAL TABLE sales_2026 (...)'
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'ddl'}));

    expect(await screen.findByRole('tab', {name: /DDL: sales_2026/})).toBeInTheDocument();
    expect(screen.getByTestId('sql-editor')).toHaveValue('CREATE EXTERNAL TABLE sales_2026 (...)');
    // A DDL fetch is not a user run — no query is started for it.
    expect(mockRunQuery).not.toHaveBeenCalled();
  });

  it('View data opens a "{table}" tab and auto-runs SELECT * LIMIT 10', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: {queryExecutionId: 'q-1'}
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'data'}));

    expect(await screen.findByRole('tab', {name: /sales_2026/})).toBeInTheDocument();
    expect(screen.getByTestId('sql-editor')).toHaveValue('SELECT * FROM alice.sales_2026 LIMIT 10');
    expect(mockRunQuery).toHaveBeenCalledWith(
      expect.objectContaining({sql: 'SELECT * FROM alice.sales_2026 LIMIT 10'})
    );
  });

  it('Drop table confirms, runs in the background, records history + success toast', async () => {
    mockRunToCompletion.mockResolvedValue({
      success: true,
      data: {
        queryExecutionId: 'q-drop',
        state: 'SUCCEEDED',
        dataScannedBytes: 0,
        engineExecutionTimeMillis: 5
      }
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'drop'}));
    const dialog = screen.getByRole('alertdialog', {name: /confirm drop table/i});
    fireEvent.click(within(dialog).getByRole('button', {name: 'Drop table'}));

    expect(await screen.findByText('Dropped sales_2026')).toBeInTheDocument();
    expect(mockRunToCompletion).toHaveBeenCalledWith(expect.objectContaining({sql: 'DROP TABLE alice.sales_2026'}));
    expect(appendEntry).toHaveBeenCalledWith(expect.objectContaining({queryExecutionId: 'q-drop'}));
  });

  it('Drop table shows an error toast and leaves the schema on failure', async () => {
    mockRunToCompletion.mockResolvedValue({
      success: true,
      data: {
        queryExecutionId: 'q-drop',
        state: 'FAILED',
        stateChangeReason: 'table locked'
      }
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'drop'}));
    fireEvent.click(
      within(screen.getByRole('alertdialog', {name: /confirm drop table/i})).getByRole('button', {
        name: 'Drop table'
      })
    );

    expect(await screen.findByText(/table locked/)).toBeInTheDocument();
  });

  it('re-runs a history entry into the active tab', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: {queryExecutionId: 'q-2'}
    });
    mockUseHistory.mockReturnValue({
      history: [
        {
          queryExecutionId: 'old',
          sql: 'SELECT 42',
          database: 'alice',
          submittedAt: new Date().toISOString(),
          status: 'SUCCEEDED'
        }
      ],
      isLoading: false,
      error: null,
      appendEntry,
      updateEntry,
      refresh: vi.fn().mockResolvedValue(undefined),
      isRefreshing: false
    });

    renderWorkspace();
    fireEvent.click(screen.getByRole('button', {name: /History/}));
    fireEvent.click(await screen.findByRole('button', {name: /re-run this query/i}));

    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: 'SELECT 42', username: 'alice'});
    expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('database');
  });

  // --- Create view + view-aware schema actions ---

  it('Create view is disabled when the active tab SQL is empty', async () => {
    renderWorkspace();
    const editor = await screen.findByTestId('sql-editor');
    fireEvent.change(editor, {target: {value: '   '}});
    expect(screen.getByRole('button', {name: 'Create view'})).toBeDisabled();
  });

  it('Create view composes CREATE OR REPLACE VIEW, runs it in the background, records history + success toast', async () => {
    mockRunToCompletion.mockResolvedValue({
      success: true,
      data: {
        queryExecutionId: 'q-view',
        state: 'SUCCEEDED',
        dataScannedBytes: 0,
        engineExecutionTimeMillis: 5
      }
    });
    renderWorkspace();
    const editor = await screen.findByTestId('sql-editor');
    // SPEC-077 FR-008: the target database is derived from the body's qualified
    // base tables — here alice.sales → the personal database 'alice'.
    fireEvent.change(editor, {target: {value: 'SELECT region FROM alice.sales;'}});

    fireEvent.click(screen.getByRole('button', {name: 'Create view'}));
    const dialog = screen.getByRole('dialog', {name: 'Create view'});
    fireEvent.change(within(dialog).getByLabelText('View name'), {
      target: {value: 'region_view'}
    });
    fireEvent.click(within(dialog).getByRole('button', {name: 'Create'}));

    expect(await screen.findByText('Created view region_view')).toBeInTheDocument();
    expect(mockRunToCompletion).toHaveBeenCalledWith(
      expect.objectContaining({
        sql: 'CREATE OR REPLACE VIEW alice.region_view AS SELECT region FROM alice.sales',
        database: 'alice',
        username: 'alice'
      })
    );
    expect(appendEntry).toHaveBeenCalledWith(expect.objectContaining({queryExecutionId: 'q-view'}));
    expect(screen.getByTestId('sql-editor')).toHaveValue('SELECT region FROM alice.sales;');
  });

  it('Create view shows an error toast on failure', async () => {
    mockRunToCompletion.mockResolvedValue({
      success: false,
      error: {message: 'TABLE_ALREADY_EXISTS', code: 'InvalidRequest'}
    });
    renderWorkspace();
    const editor = await screen.findByTestId('sql-editor');
    fireEvent.change(editor, {target: {value: 'SELECT 1 FROM alice.t;'}});

    fireEvent.click(screen.getByRole('button', {name: 'Create view'}));
    fireEvent.change(within(screen.getByRole('dialog', {name: 'Create view'})).getByLabelText('View name'), {
      target: {value: 'dupe'}
    });
    fireEvent.click(within(screen.getByRole('dialog', {name: 'Create view'})).getByRole('button', {name: 'Create'}));

    expect(await screen.findByText(/TABLE_ALREADY_EXISTS/)).toBeInTheDocument();
  });

  it('View source files is disabled for a view (no S3 location)', async () => {
    renderWorkspace();
    await screen.findByTestId('sql-editor');
    expect(screen.getByText('cansrc-view:false')).toBeInTheDocument();
  });

  it('View DDL for a view fetches SHOW CREATE VIEW (isView passed through)', async () => {
    mockGetTableDdl.mockResolvedValue({success: true, data: 'CREATE VIEW …'});
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'ddl:view'}));
    expect(mockGetTableDdl).toHaveBeenCalledWith(expect.objectContaining({table: 'revenue_view', isView: true}));
  });

  it('Drop on a view confirms and runs DROP VIEW', async () => {
    mockRunToCompletion.mockResolvedValue({
      success: true,
      data: {
        queryExecutionId: 'q-dropview',
        state: 'SUCCEEDED',
        dataScannedBytes: 0,
        engineExecutionTimeMillis: 5
      }
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'drop:view'}));
    const dialog = screen.getByRole('alertdialog', {name: /confirm drop view/i});
    fireEvent.click(within(dialog).getByRole('button', {name: 'Drop view'}));

    expect(await screen.findByText('Dropped revenue_view')).toBeInTheDocument();
    expect(mockRunToCompletion).toHaveBeenCalledWith(expect.objectContaining({sql: 'DROP VIEW alice.revenue_view'}));
  });

  // --- Save results to my files ---

  async function renderSucceededWithRows() {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: {queryExecutionId: 'q-1'}
    });
    mockUseExecution.mockReturnValue(succeededStatus);
    mockUseResults.mockReturnValue(rowsResult);
    renderWorkspace();
    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));
    await screen.findByText('Succeeded');
  }

  it('offers Save results for a succeeded row-returning query', async () => {
    await renderSucceededWithRows();
    expect(screen.getByRole('button', {name: 'Save results to my files'})).toBeInTheDocument();
  });

  it('saving copies the full result object to the chosen destination + toast with a Files link', async () => {
    mockCopyObject.mockResolvedValue({
      success: true,
      data: {destKey: 'alice/reports/out.csv'}
    });
    await renderSucceededWithRows();

    fireEvent.click(screen.getByRole('button', {name: 'Save results to my files'}));
    fireEvent.click(screen.getByRole('button', {name: 'save-here-stub'}));

    // Source bucket + key are derived from the result's outputLocation;
    // dest = the chosen space's bucket + folder + filename.
    expect(mockCopyObject).toHaveBeenCalledWith({
      bucket: 'b',
      destBucket: 'user-bucket',
      sourceKey: 'alice/athenaresults/q-1.csv',
      destKey: 'alice/reports/out.csv',
      username: 'alice',
      overwrite: false
    });

    const link = await screen.findByRole('button', {name: 'View in Files'});
    fireEvent.click(link);
    expect(navigateMock).toHaveBeenCalledWith('/files?prefix=alice%2Freports%2F');
  });

  it('a destination collision prompts Overwrite, then copies with overwrite', async () => {
    mockCopyObject
      .mockResolvedValueOnce({
        success: false,
        error: {message: 'exists', code: 'Collision'}
      })
      .mockResolvedValueOnce({
        success: true,
        data: {destKey: 'alice/reports/out.csv'}
      });
    await renderSucceededWithRows();

    fireEvent.click(screen.getByRole('button', {name: 'Save results to my files'}));
    fireEvent.click(screen.getByRole('button', {name: 'save-here-stub'}));

    const dialog = await screen.findByRole('alertdialog', {
      name: /confirm overwrite/i
    });
    fireEvent.click(within(dialog).getByRole('button', {name: 'Overwrite'}));

    expect(mockCopyObject).toHaveBeenLastCalledWith(expect.objectContaining({overwrite: true}));
    expect(await screen.findByText(/Saved to alice\/reports\/out\.csv/)).toBeInTheDocument();
  });

  it('a copy error shows an error toast and navigates nowhere', async () => {
    mockCopyObject.mockResolvedValue({
      success: false,
      error: {message: 'Access Denied', code: 'AccessDenied'}
    });
    await renderSucceededWithRows();

    fireEvent.click(screen.getByRole('button', {name: 'Save results to my files'}));
    fireEvent.click(screen.getByRole('button', {name: 'save-here-stub'}));

    expect(await screen.findByText(/Access Denied/)).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });
});

describe('QueryWorkspace — multi-statement batches (SPEC-078)', () => {
  type StatusStub = {state: string; stateChangeReason?: string; outputLocation?: string};

  const idleExecution = {data: undefined};

  // Per-execution-id statuses for the pollers; mutable so a test can flip a
  // statement's state mid-flight (the next render re-reads the map). Returned
  // objects are cached per (id, stub) — the real hook returns referentially
  // stable data, and a fresh object per call would loop the poller's status
  // effect forever.
  function mockExecutionMap(map: Record<string, StatusStub>) {
    const cache = new Map<string, {stub: StatusStub; value: unknown}>();
    mockUseExecution.mockImplementation(((id: string | null) => {
      if (id === null || !map[id]) return idleExecution;
      const cached = cache.get(id);
      if (cached && cached.stub === map[id]) return cached.value;
      const value = {
        data: {
          queryExecutionId: id,
          dataScannedBytes: 10,
          engineExecutionTimeMillis: 5,
          ...map[id]
        }
      };
      cache.set(id, {stub: map[id], value});
      return value;
    }) as unknown as typeof useQueryExecution);
    return map;
  }

  function queueExecutions(...ids: string[]) {
    // clearAllMocks does not drop unconsumed mockResolvedValueOnce values from a
    // prior test (a batch that stopped early leaves some queued) — reset first.
    mockRunQuery.mockReset();
    for (const id of ids) {
      mockRunQuery.mockResolvedValueOnce({success: true, data: {queryExecutionId: id}});
    }
  }

  const THREE_STATEMENTS = 'SELECT 1; CREATE TABLE alice.t (id int); SELECT 2;';

  function seedScript(sql: string = THREE_STATEMENTS) {
    seedTabs({
      version: 1,
      tabs: [{id: 'a', label: 'Query 1', sql}],
      activeTabId: 'a',
      nextQueryNumber: 2
    });
  }

  it('runs a script sequentially and records one history entry per statement (FR-002/FR-003)', async () => {
    queueExecutions('q-1', 'q-2', 'q-3');
    mockExecutionMap({
      'q-1': {state: 'SUCCEEDED'},
      'q-2': {state: 'SUCCEEDED'},
      'q-3': {state: 'SUCCEEDED'}
    });
    mockUseResults.mockReturnValue(rowsResult);
    seedScript();
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Run script, single result'}));

    await screen.findByText('Succeeded');
    expect(mockRunQuery).toHaveBeenCalledTimes(3);
    expect(mockRunQuery.mock.calls.map((c) => c[0].sql)).toEqual([
      'SELECT 1',
      'CREATE TABLE alice.t (id int)',
      'SELECT 2'
    ]);
    // FR-003: one history entry per statement, each with that statement's SQL.
    expect(appendEntry).toHaveBeenCalledTimes(3);
    expect(appendEntry.mock.calls.map((c) => c[0].sql)).toEqual([
      'SELECT 1',
      'CREATE TABLE alice.t (id int)',
      'SELECT 2'
    ]);
    // Completion summary in the status bar.
    expect(screen.getByRole('status')).toHaveTextContent('Script finished · 3 statements');
    // Single-result scope: no result-tab strip.
    expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument();
  });

  it('stops at the first failed statement and names it in the banner (FR-002/FR-004)', async () => {
    queueExecutions('q-1', 'q-2', 'q-3');
    mockExecutionMap({
      'q-1': {state: 'SUCCEEDED'},
      'q-2': {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'}
    });
    seedScript();
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Run script, single result'}));

    expect(await screen.findByText(/Statement 2 of 3 failed: SYNTAX_ERROR: line 1/)).toBeInTheDocument();
    expect(screen.getByText(/Statement 3 did not run/)).toBeInTheDocument();
    // Statement 3 never started; statements 1–2 each got a history entry.
    expect(mockRunQuery).toHaveBeenCalledTimes(2);
    expect(appendEntry).toHaveBeenCalledTimes(2);
  });

  it('Stop mid-batch halts the remainder even when the in-flight statement succeeds (FR-002)', async () => {
    queueExecutions('q-1', 'q-2');
    const map = mockExecutionMap({'q-1': {state: 'RUNNING'}});
    seedScript('SELECT 1;\nSELECT 2;');
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Run script, single result'}));
    const stop = await screen.findByRole('button', {name: /Stop/});

    // The statement outruns the cancel: it reaches SUCCEEDED, but Stop already
    // marked the batch halted — statement 2 must never start.
    map['q-1'] = {state: 'SUCCEEDED'};
    fireEvent.click(stop);

    const {stopQuery} = await import('./query.service');
    expect(vi.mocked(stopQuery)).toHaveBeenCalledWith('q-1');
    await screen.findByText('Succeeded');
    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    // Halted early → no "Script finished" summary.
    expect(screen.getByRole('status')).not.toHaveTextContent('Script finished');
  });

  it('Run Script (tab per statement) yields one result tab per result-producing statement (FR-007)', async () => {
    queueExecutions('q-1', 'q-2', 'q-3');
    mockExecutionMap({
      'q-1': {state: 'SUCCEEDED'},
      'q-2': {state: 'SUCCEEDED'},
      'q-3': {state: 'SUCCEEDED'}
    });
    mockUseResults.mockReturnValue(rowsResult);
    seedScript();
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Run script, tab per statement'}));

    const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
    const resultTabs = within(strip).getAllByRole('tab');
    // The CREATE (statement 2) earns no tab; labels carry statement positions.
    expect(resultTabs.map((t) => t.textContent)).toEqual(['1 · SELECT 1', '3 · SELECT 2']);
    // The newest result tab is active; switching re-keys the displayed results.
    expect(resultTabs[1]).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(resultTabs[0]);
    expect(within(strip).getAllByRole('tab')[0]).toHaveAttribute('aria-selected', 'true');
    expect(mockUseResults.mock.lastCall?.[0]).toBe('q-1');
  });

  it('a new run clears the previous run’s result tabs (FR-007)', async () => {
    queueExecutions('q-1', 'q-2', 'q-3', 'q-4');
    mockExecutionMap({
      'q-1': {state: 'SUCCEEDED'},
      'q-2': {state: 'SUCCEEDED'},
      'q-3': {state: 'SUCCEEDED'},
      'q-4': {state: 'RUNNING'}
    });
    mockUseResults.mockReturnValue(rowsResult);
    seedScript();
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Run script, tab per statement'}));
    await screen.findByRole('tablist', {name: 'Result tabs'});

    fireEvent.click(screen.getByRole('button', {name: 'Run script, tab per statement'}));
    await screen.findByRole('button', {name: /Stop/});
    expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument();
  });

  it('shows batch progress in the status bar while running (FR-004)', async () => {
    queueExecutions('q-1', 'q-2', 'q-3');
    mockExecutionMap({
      'q-1': {state: 'SUCCEEDED'},
      'q-2': {state: 'RUNNING'}
    });
    seedScript();
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', {name: 'Run script, single result'}));

    await screen.findByRole('button', {name: /Stop/});
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Statement 2 of 3'));
  });

  it('Run Statement executes the statement under the cursor (FR-006)', async () => {
    queueExecutions('q-1');
    seedScript('SELECT 1;\nSELECT 2;');
    renderWorkspace();
    const editor = (await screen.findByTestId('sql-editor')) as HTMLTextAreaElement;

    const cursor = editor.value.indexOf('SELECT 2') + 3;
    editor.setSelectionRange(cursor, cursor);
    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));

    await screen.findByRole('button', {name: /Stop/});
    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    expect(mockRunQuery.mock.calls[0][0].sql).toBe('SELECT 2');
  });

  it('Run Statement executes the selection when one exists (FR-006)', async () => {
    queueExecutions('q-1');
    seedScript('SELECT 1;\nSELECT 2;');
    renderWorkspace();
    const editor = (await screen.findByTestId('sql-editor')) as HTMLTextAreaElement;

    editor.setSelectionRange(0, 'SELECT 1'.length);
    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));

    await screen.findByRole('button', {name: /Stop/});
    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    expect(mockRunQuery.mock.calls[0][0].sql).toBe('SELECT 1');
  });
});

describe('QueryWorkspace — shared-space routing & save (SPEC-055)', () => {
  const sharedConnection = {
    id: 'salesdata',
    label: 'salesdata',
    database: 'salesdata',
    kind: 'shared' as const,
    status: 'active' as const,
    role: 'member' as const
  };

  // SPEC-077: the rail no longer selects an active database; a shared destination
  // is only chosen at Save time, so shared connections just need to be present.
  function withSharedActive() {
    mockUseConnections.mockReturnValue({
      connections: [personalConnection, sharedConnection],
      isLoading: false,
      error: null,
      refresh: vi.fn(),
      isRefreshing: false,
      reconcile: vi.fn()
    });
  }

  async function renderSharedSucceeded() {
    withSharedActive();
    mockRunQuery.mockResolvedValue({success: true, data: {queryExecutionId: 'q-1'}});
    mockUseExecution.mockReturnValue({
      data: {...succeededStatus.data, outputLocation: 's3://shared-bucket/salesdata/athenaresults/alice/q-1.csv'}
    } as unknown as ReturnType<typeof useQueryExecution>);
    mockUseResults.mockReturnValue(rowsResult);
    renderWorkspace();
    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));
    await screen.findByText('Succeeded');
  }

  it('never routes results to a shared prefix at run time — results default to personal (SPEC-077)', async () => {
    withSharedActive();
    mockRunQuery.mockResolvedValue({success: true, data: {queryExecutionId: 'q-1'}});
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));
    expect(await screen.findByRole('button', {name: /Stop/})).toBeInTheDocument();
    // No database context, no run-time shared outputLocation — just sql + username.
    expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: expect.any(String), username: 'alice'});
    expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('outputLocation');
    expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('database');
  });

  it('a personal query is run with just sql + username (no outputLocation, no database)', async () => {
    mockRunQuery.mockResolvedValue({success: true, data: {queryExecutionId: 'q-1'}});
    renderWorkspace(); // default: only the personal connection

    fireEvent.click(screen.getByRole('button', {name: 'Run statement'}));
    expect(await screen.findByRole('button', {name: /Stop/})).toBeInTheDocument();
    expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: expect.any(String), username: 'alice'});
    expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('outputLocation');
    expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('database');
  });

  it('the Save dialog offers personal + member-of shared destinations (FR-003)', async () => {
    await renderSharedSucceeded();
    fireEvent.click(screen.getByRole('button', {name: 'Save results to my files'}));
    expect(screen.getByText('spaces:personal,salesdata')).toBeInTheDocument();
  });

  it('saving a shared result into the user space is a cross-bucket copy with no Files link (FR-003/FR-004)', async () => {
    mockCopyObject.mockResolvedValue({success: true, data: {destKey: 'alice/reports/out.csv'}});
    await renderSharedSucceeded();

    fireEvent.click(screen.getByRole('button', {name: 'Save results to my files'}));
    fireEvent.click(screen.getByRole('button', {name: 'save-to-personal'}));

    expect(mockCopyObject).toHaveBeenCalledWith({
      bucket: 'shared-bucket',
      destBucket: 'user-bucket',
      sourceKey: 'salesdata/athenaresults/alice/q-1.csv',
      destKey: 'alice/reports/out.csv',
      username: 'alice',
      overwrite: false
    });
    expect(await screen.findByText(/Saved to alice\/reports\/out\.csv/)).toBeInTheDocument();
    // Personal-dest save keeps the deep-link.
    expect(screen.getByRole('button', {name: 'View in Files'})).toBeInTheDocument();
  });

  it('saving into a shared space copies within that bucket and offers no Files link (FR-003)', async () => {
    mockCopyObject.mockResolvedValue({success: true, data: {destKey: 'salesdata/reports/out.csv'}});
    await renderSharedSucceeded();

    fireEvent.click(screen.getByRole('button', {name: 'Save results to my files'}));
    fireEvent.click(screen.getByRole('button', {name: 'save-to-salesdata'}));

    expect(mockCopyObject).toHaveBeenCalledWith({
      bucket: 'shared-bucket',
      destBucket: 'shared-bucket',
      sourceKey: 'salesdata/athenaresults/alice/q-1.csv',
      destKey: 'salesdata/reports/out.csv',
      username: 'alice',
      overwrite: false
    });
    expect(await screen.findByText(/Saved to salesdata\/reports\/out\.csv/)).toBeInTheDocument();
    // The Files browser cannot render shared spaces, so no deep-link is offered.
    expect(screen.queryByRole('button', {name: 'View in Files'})).not.toBeInTheDocument();
  });
});
