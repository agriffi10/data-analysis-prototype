import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Auth + the lazy editor + the data hooks are mocked so the workspace can be
// exercised without Amplify, Monaco workers, or live AWS calls.
vi.mock('../auth', () => ({
  useAuth: () => ({ user: { username: 'alice' }, status: 'authenticated' }),
}));
vi.mock('./SqlEditor', () => ({
  // Render the value so restore-on-mount / Clear are observable in tests.
  SqlEditor: ({ value }: { value: string }) => (
    <div data-testid="sql-editor">{value}</div>
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
import { QUERY_DRAFT_STORAGE_PREFIX } from './query.constants';

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

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  // Default: no execution in flight, no results.
  mockUseExecution.mockReturnValue({ data: undefined } as unknown as ReturnType<
    typeof useQueryExecution
  >);
  mockUseResults.mockReturnValue({
    columns: [],
    rows: [],
    pageIndex: 0,
    rangeStart: 0,
    rangeEnd: 0,
    loadedRowCount: 0,
    totalRowCount: 0,
    hasPrev: false,
    hasNext: false,
    hasMoreServer: false,
    isPending: false,
    isFetchingNext: false,
    isError: false,
    error: null,
    goPrev: vi.fn(),
    goNext: vi.fn(),
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
  it('renders the workspace with the database chip and an enabled Run', async () => {
    renderWorkspace();

    expect(screen.getByTestId('schema-browser')).toBeInTheDocument();
    expect(await screen.findByTestId('sql-editor')).toBeInTheDocument(); // lazy
    expect(screen.getAllByText('alice').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /Run/ })).toBeEnabled();
  });

  it('runs the query against the user database and records history on submit', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: { queryExecutionId: 'q-1' },
    });
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', { name: /Run/ }));

    // Execution now in flight → Stop replaces Run (awaits the post-run state).
    expect(
      await screen.findByRole('button', { name: /Stop/ }),
    ).toBeInTheDocument();
    expect(mockRunQuery).toHaveBeenCalledTimes(1);
    expect(mockRunQuery.mock.calls[0][0]).toMatchObject({
      database: 'alice',
      username: 'alice',
    });
    expect(appendEntry).toHaveBeenCalledTimes(1);
    expect(appendEntry.mock.calls[0][0]).toMatchObject({
      queryExecutionId: 'q-1',
      database: 'alice',
    });
  });

  it('surfaces a runQuery error in a danger banner', async () => {
    mockRunQuery.mockResolvedValue({
      success: false,
      error: { message: 'COLUMN_NOT_FOUND: amont', code: 'InvalidRequest' },
    });
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', { name: /Run/ }));

    expect(await screen.findByText(/COLUMN_NOT_FOUND/)).toBeInTheDocument();
    // No execution id was set, so Run remains (not Stop).
    expect(screen.getByRole('button', { name: /Run/ })).toBeInTheDocument();
  });

  it('shows the results table once the execution has succeeded', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: { queryExecutionId: 'q-1' },
    });
    // The execution hook reports SUCCEEDED, and results carry one page of rows.
    mockUseExecution.mockReturnValue({
      data: {
        queryExecutionId: 'q-1',
        state: 'SUCCEEDED',
        dataScannedBytes: 2048,
        engineExecutionTimeMillis: 800,
        outputLocation: 's3://b/alice/athenaresults/q-1.csv',
      },
    } as unknown as ReturnType<typeof useQueryExecution>);
    mockUseResults.mockReturnValue({
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
    } as unknown as ReturnType<typeof useQueryResults>);

    renderWorkspace();
    // Run sets the execution id, which gates the status bar + results.
    fireEvent.click(screen.getByRole('button', { name: /Run/ }));

    expect(await screen.findByText('Succeeded')).toBeInTheDocument();
    expect(screen.getByText('region')).toBeInTheDocument();
    expect(screen.getByText('us-east')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Download CSV/ }),
    ).toBeInTheDocument();
  });

  it('seeds the editor from the persisted draft on mount (SPEC-040)', async () => {
    sessionStorage.setItem(
      `${QUERY_DRAFT_STORAGE_PREFIX}alice`,
      'SELECT * FROM persisted;',
    );
    renderWorkspace();

    const editor = await screen.findByTestId('sql-editor');
    expect(editor).toHaveTextContent('SELECT * FROM persisted;');
  });

  it('falls back to the default boilerplate when no draft exists (SPEC-040)', async () => {
    renderWorkspace();

    const editor = await screen.findByTestId('sql-editor');
    expect(editor).toHaveTextContent('SELECT 1;');
  });

  it('Clear confirms, then empties the editor + draft and disables Run (SPEC-040)', async () => {
    sessionStorage.setItem(
      `${QUERY_DRAFT_STORAGE_PREFIX}alice`,
      'SELECT * FROM persisted;',
    );
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    // Clicking Clear opens a warn-and-confirm dialog; the editor is untouched yet.
    fireEvent.click(screen.getByRole('button', { name: 'Clear query' }));
    const dialog = screen.getByRole('alertdialog', {
      name: /confirm clear query/i,
    });
    expect(screen.getByTestId('sql-editor')).toHaveTextContent(
      'SELECT * FROM persisted;',
    );

    // Confirm → editor empties, the persisted draft is removed, Run disabled.
    fireEvent.click(within(dialog).getByRole('button', { name: 'Clear' }));
    expect(screen.getByTestId('sql-editor')).toHaveTextContent('');
    expect(
      sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`),
    ).toBeNull();
    expect(screen.getByRole('button', { name: /Run/ })).toBeDisabled();
    // Clear itself is now disabled (editor empty).
    expect(screen.getByRole('button', { name: 'Clear query' })).toBeDisabled();
  });

  it('Clear cancel leaves the editor untouched (SPEC-040)', async () => {
    sessionStorage.setItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`, 'SELECT keep;');
    renderWorkspace();
    await screen.findByTestId('sql-editor');

    fireEvent.click(screen.getByRole('button', { name: 'Clear query' }));
    const dialog = screen.getByRole('alertdialog', {
      name: /confirm clear query/i,
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(screen.getByTestId('sql-editor')).toHaveTextContent('SELECT keep;');
    expect(sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`)).toBe(
      'SELECT keep;',
    );
  });

  it('disables Clear while a query is in flight (SPEC-040)', async () => {
    mockRunQuery.mockResolvedValue({
      success: true,
      data: { queryExecutionId: 'q-1' },
    });
    mockUseExecution.mockReturnValue({
      data: { queryExecutionId: 'q-1', state: 'RUNNING' },
    } as unknown as ReturnType<typeof useQueryExecution>);

    renderWorkspace();
    fireEvent.click(screen.getByRole('button', { name: /Run/ }));

    // In flight → Stop replaces Run, and Clear is disabled.
    expect(await screen.findByRole('button', { name: /Stop/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear query' })).toBeDisabled();
  });

  it('re-runs a history entry from the history panel', async () => {
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
