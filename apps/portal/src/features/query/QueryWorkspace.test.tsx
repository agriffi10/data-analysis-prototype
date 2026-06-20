import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Auth + the lazy editor + the data hooks are mocked so the workspace can be
// exercised without Amplify, Monaco workers, or live AWS calls. useQueryTabs is
// NOT mocked — it's a pure state hook and we want real tab behavior under test.
vi.mock('../auth', () => ({
  useAuth: () => ({ user: { username: 'alice' }, status: 'authenticated' }),
}));
vi.mock('./SqlEditor', () => ({
  // A textarea wired to value/onChange so per-tab text + switching is observable.
  SqlEditor: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (v: string) => void;
  }) => (
    <textarea
      data-testid="sql-editor"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));
vi.mock('./SchemaBrowser', () => ({
  SchemaBrowser: () => <div data-testid="schema-browser" />,
}));
vi.mock('./query.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./query.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getResultCsvUrl: vi.fn(),
}));
vi.mock('./useQueryExecution', () => ({ useQueryExecution: vi.fn() }));
vi.mock('./useQueryResults', () => ({ useQueryResults: vi.fn() }));
vi.mock('./useQueryHistory', () => ({ useQueryHistory: vi.fn() }));

import { runQuery } from './query.service';
import { useQueryExecution } from './useQueryExecution';
import { useQueryResults } from './useQueryResults';
import { useQueryHistory } from './useQueryHistory';
import { QueryWorkspace } from './QueryWorkspace';
import {
  QUERY_DRAFT_STORAGE_PREFIX,
  QUERY_TABS_STORAGE_PREFIX,
} from './query.constants';
import type { QueryTabsState } from './query.types';

const mockRunQuery = vi.mocked(runQuery);
const mockUseExecution = vi.mocked(useQueryExecution);
const mockUseResults = vi.mocked(useQueryResults);
const mockUseHistory = vi.mocked(useQueryHistory);

const appendEntry = vi.fn().mockResolvedValue({ version: 1, entries: [] });
const updateEntry = vi.fn().mockResolvedValue({ version: 1, entries: [] });

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <QueryWorkspace />
    </QueryClientProvider>,
  );
}

function seedTabs(state: QueryTabsState) {
  sessionStorage.setItem(
    `${QUERY_TABS_STORAGE_PREFIX}alice`,
    JSON.stringify(state),
  );
}

const succeededStatus = {
  data: {
    queryExecutionId: 'q-1',
    state: 'SUCCEEDED',
    dataScannedBytes: 2048,
    engineExecutionTimeMillis: 800,
    outputLocation: 's3://b/alice/athenaresults/q-1.csv',
  },
} as unknown as ReturnType<typeof useQueryExecution>;

const rowsResult = {
  columns: [{ name: 'region', type: 'string' }],
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
  goNext: vi.fn(),
} as unknown as ReturnType<typeof useQueryResults>;

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  // Default: no execution in flight, no results.
  mockUseExecution.mockReturnValue({ data: undefined } as unknown as ReturnType<
    typeof useQueryExecution
  >);
  mockUseResults.mockReturnValue({
    ...rowsResult,
    columns: [],
    rows: [],
    rangeStart: 0,
    rangeEnd: 0,
    loadedRowCount: 0,
    totalRowCount: 0,
  } as unknown as ReturnType<typeof useQueryResults>);
  mockUseHistory.mockReturnValue({
    history: [],
    isLoading: false,
    error: null,
    appendEntry,
    updateEntry,
  });
});

describe('QueryWorkspace', () => {
  it('renders the workspace with a Query 1 tab, db chip, and enabled Run', async () => {
    renderWorkspace();

    expect(screen.getByTestId('schema-browser')).toBeInTheDocument();
    expect(await screen.findByTestId('sql-editor')).toBeInTheDocument(); // lazy
    expect(screen.getByRole('tab', { name: /Query 1/ })).toBeInTheDocument();
    expect(screen.getAllByText('alice').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /Run/ })).toBeEnabled();
  });

  it('runs the active tab and records history on submit', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: { queryExecutionId: 'q-1' },
    });
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', { name: /Run/ }));

    expect(
      await screen.findByRole('button', { name: /Stop/ }),
    ).toBeInTheDocument();
    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    expect(mockRunQuery.mock.calls[0][0]).toMatchObject({
      database: 'alice',
      username: 'alice',
    });
    expect(appendEntry).toHaveBeenCalledTimes(1);
  });

  it('surfaces a runQuery error in a danger banner', async () => {
    mockRunQuery.mockResolvedValue({
      success: false,
      error: { message: 'COLUMN_NOT_FOUND: amont', code: 'InvalidRequest' },
    });
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', { name: /Run/ }));

    expect(await screen.findByText(/COLUMN_NOT_FOUND/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Run/ })).toBeInTheDocument();
  });

  it('shows the results table once the active execution has succeeded', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: { queryExecutionId: 'q-1' },
    });
    mockUseExecution.mockReturnValue(succeededStatus);
    mockUseResults.mockReturnValue(rowsResult);

    renderWorkspace();
    fireEvent.click(screen.getByRole('button', { name: /Run/ }));

    expect(await screen.findByText('Succeeded')).toBeInTheDocument();
    expect(screen.getByText('region')).toBeInTheDocument();
    expect(screen.getByText('us-east')).toBeInTheDocument();
  });

  // --- SPEC-041 persistence + migration ---

  it('restores tabs from persisted state on mount, showing the active tab text', async () => {
    seedTabs({
      version: 1,
      tabs: [
        { id: 'a', label: 'Query 1', sql: 'SELECT one;' },
        { id: 'b', label: 'Scratch', sql: 'SELECT two;' },
      ],
      activeTabId: 'b',
      nextQueryNumber: 2,
    });
    renderWorkspace();

    expect(await screen.findByTestId('sql-editor')).toHaveValue('SELECT two;');
    expect(screen.getByRole('tab', { name: /Scratch/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('migrates a SPEC-040 draft into tab 1 on first load (back-compat)', async () => {
    sessionStorage.setItem(
      `${QUERY_DRAFT_STORAGE_PREFIX}alice`,
      'SELECT migrated;',
    );
    renderWorkspace();

    expect(await screen.findByTestId('sql-editor')).toHaveValue('SELECT migrated;');
    // The old draft key is consumed by the migration.
    expect(
      sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`),
    ).toBeNull();
  });

  // --- SPEC-041 tabs behavior ---

  it('opens a new blank Query 2 tab and isolates text per tab', async () => {
    renderWorkspace();
    const editor = await screen.findByTestId('sql-editor');

    fireEvent.change(editor, { target: { value: 'SELECT a;' } });
    fireEvent.click(screen.getByRole('button', { name: 'New query tab' }));

    // New tab is blank and active.
    expect(screen.getByRole('tab', { name: /Query 2/ })).toBeInTheDocument();
    expect(screen.getByTestId('sql-editor')).toHaveValue('');
    fireEvent.change(screen.getByTestId('sql-editor'), {
      target: { value: 'SELECT b;' },
    });

    // Switch back to Query 1 — its text is intact, untouched by Query 2.
    fireEvent.click(screen.getByRole('tab', { name: /Query 1/ }));
    expect(screen.getByTestId('sql-editor')).toHaveValue('SELECT a;');
    fireEvent.click(screen.getByRole('tab', { name: /Query 2/ }));
    expect(screen.getByTestId('sql-editor')).toHaveValue('SELECT b;');
  });

  it('closes an empty tab immediately but confirms a non-empty one', async () => {
    seedTabs({
      version: 1,
      tabs: [
        { id: 'a', label: 'Query 1', sql: 'SELECT keep;' },
        { id: 'b', label: 'Query 2', sql: '' },
      ],
      activeTabId: 'a',
      nextQueryNumber: 3,
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    // Empty Query 2 closes with no dialog.
    fireEvent.click(screen.getByRole('button', { name: 'Close Query 2' }));
    expect(screen.queryByRole('tab', { name: /Query 2/ })).not.toBeInTheDocument();

    // Query 1 is now the only tab → its close control is hidden.
    expect(
      screen.queryByRole('button', { name: 'Close Query 1' }),
    ).not.toBeInTheDocument();
  });

  it('confirms before closing a tab with non-empty SQL', async () => {
    seedTabs({
      version: 1,
      tabs: [
        { id: 'a', label: 'Query 1', sql: 'SELECT keep;' },
        { id: 'b', label: 'Query 2', sql: 'SELECT bye;' },
      ],
      activeTabId: 'a',
      nextQueryNumber: 3,
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', { name: 'Close Query 2' }));
    const dialog = screen.getByRole('alertdialog', { name: /confirm close tab/i });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close tab' }));

    expect(screen.queryByRole('tab', { name: /Query 2/ })).not.toBeInTheDocument();
  });

  it('shows the tab-limit dialog at the cap and opens no further tab', async () => {
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    const newTabBtn = screen.getByRole('button', { name: 'New query tab' });
    // 1 tab already; open 9 more to reach the cap of 10.
    for (let i = 0; i < 9; i++) fireEvent.click(newTabBtn);
    expect(screen.getAllByRole('tab')).toHaveLength(10);

    // 11th attempt raises the dialog and creates nothing.
    fireEvent.click(newTabBtn);
    expect(
      screen.getByRole('alertdialog', { name: /query tab limit reached/i }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(10);
  });

  // --- SPEC-040 Clear, now scoped to the active tab ---

  it('Clear confirms, empties the active tab, and disables Run', async () => {
    seedTabs({
      version: 1,
      tabs: [{ id: 'a', label: 'Query 1', sql: 'SELECT * FROM persisted;' }],
      activeTabId: 'a',
      nextQueryNumber: 2,
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', { name: 'Clear query' }));
    const dialog = screen.getByRole('alertdialog', {
      name: /confirm clear query/i,
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Clear' }));

    expect(screen.getByTestId('sql-editor')).toHaveValue('');
    expect(screen.getByRole('button', { name: /Run/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Clear query' })).toBeDisabled();
  });

  it('Clear cancel leaves the active tab untouched', async () => {
    seedTabs({
      version: 1,
      tabs: [{ id: 'a', label: 'Query 1', sql: 'SELECT keep;' }],
      activeTabId: 'a',
      nextQueryNumber: 2,
    });
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', { name: 'Clear query' }));
    const dialog = screen.getByRole('alertdialog', {
      name: /confirm clear query/i,
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(screen.getByTestId('sql-editor')).toHaveValue('SELECT keep;');
  });

  it('disables Clear while a query is in flight', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: { queryExecutionId: 'q-1' },
    });
    mockUseExecution.mockReturnValue({
      data: { queryExecutionId: 'q-1', state: 'RUNNING' },
    } as unknown as ReturnType<typeof useQueryExecution>);

    renderWorkspace();
    fireEvent.click(screen.getByRole('button', { name: /Run/ }));

    expect(
      await screen.findByRole('button', { name: /Stop/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear query' })).toBeDisabled();
  });

  // --- concurrent background polling (FR-004) ---

  it('finalizes a backgrounded running tab while another tab is active', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: { queryExecutionId: 'q-1' },
    });
    // Every poller observes SUCCEEDED — stands in for the background query
    // finishing while the user is elsewhere.
    mockUseExecution.mockReturnValue(succeededStatus);
    mockUseResults.mockReturnValue(rowsResult);

    renderWorkspace();
    await screen.findByTestId('sql-editor');

    // Run in Query 1 and wait for it to register (results appear).
    fireEvent.click(screen.getByRole('button', { name: /Run/ }));
    expect(await screen.findByText('region')).toBeInTheDocument();

    // Leave it for a fresh Query 2.
    fireEvent.click(screen.getByRole('button', { name: 'New query tab' }));

    // Query 2 is active with no run of its own…
    expect(screen.getByText('Run a query to see results.')).toBeInTheDocument();
    // …yet Query 1's execution finalized in the background.
    expect(updateEntry).toHaveBeenCalledWith(
      expect.objectContaining({ queryExecutionId: 'q-1' }),
    );

    // Returning to Query 1 shows its already-ready results.
    fireEvent.click(screen.getByRole('tab', { name: /Query 1/ }));
    expect(screen.getByText('region')).toBeInTheDocument();
  });

  it('re-runs a history entry into the active tab', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: { queryExecutionId: 'q-2' },
    });
    mockUseHistory.mockReturnValue({
      history: [
        {
          queryExecutionId: 'old',
          sql: 'SELECT 42',
          database: 'alice',
          submittedAt: new Date().toISOString(),
          status: 'SUCCEEDED',
        },
      ],
      isLoading: false,
      error: null,
      appendEntry,
      updateEntry,
    });

    renderWorkspace();
    fireEvent.click(screen.getByRole('button', { name: /History/ }));
    fireEvent.click(await screen.findByRole('button', { name: 'Re-run' }));

    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    expect(mockRunQuery.mock.calls[0][0]).toMatchObject({
      sql: 'SELECT 42',
      database: 'alice',
    });
  });
});
