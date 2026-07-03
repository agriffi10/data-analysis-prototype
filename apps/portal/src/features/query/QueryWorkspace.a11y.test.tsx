import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS} from '../../test/axe';

// Render the real workspace in a populated, succeeded state: schema tables (real
// SchemaBrowser over a mocked useSchema), the editor (Monaco stubbed as a labelled
// textarea), and a succeeded result set. Only the data layer / lazy editor are
// mocked — the structure under axe is the real one.
vi.mock('../auth', () => ({
  useAuth: () => ({user: {username: 'alice'}, status: 'authenticated'})
}));
vi.mock('./SqlEditor', () => ({
  SqlEditor: ({value, onChange}: {value: string; onChange: (v: string) => void}) => (
    <textarea
      aria-label="SQL editor"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}));
vi.mock('./useSchema', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./useSchema')>()),
  useSchema: vi.fn()
}));
vi.mock('./query.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./query.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn()
}));
vi.mock('./useQueryExecution', () => ({useQueryExecution: vi.fn()}));
vi.mock('./useQueryResults', () => ({useQueryResults: vi.fn()}));
vi.mock('./useQueryHistory', () => ({useQueryHistory: vi.fn()}));
vi.mock('./useSavedQueries', () => ({useSavedQueries: vi.fn()}));

import {useSchema} from './useSchema';
import {useQueryExecution} from './useQueryExecution';
import {useQueryResults} from './useQueryResults';
import {useQueryHistory} from './useQueryHistory';
import {useSavedQueries} from './useSavedQueries';
import {QueryWorkspace} from './QueryWorkspace';

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
  vi.mocked(useSchema).mockReturnValue({
    data: {
      database: {name: 'alice'},
      tables: [
        {
          name: 'sales_2026',
          location: 's3://b/alice/sales/',
          columns: [{name: 'region', type: 'string'}]
        }
      ]
    },
    isPending: false,
    isError: false,
    error: null
  } as unknown as ReturnType<typeof useSchema>);
  vi.mocked(useQueryExecution).mockReturnValue(succeededStatus);
  vi.mocked(useQueryResults).mockReturnValue(rowsResult);
  vi.mocked(useQueryHistory).mockReturnValue({
    history: [],
    isLoading: false,
    error: null,
    appendEntry: vi.fn().mockResolvedValue({version: 1, entries: []}),
    updateEntry: vi.fn().mockResolvedValue({version: 1, entries: []}),
    refresh: vi.fn().mockResolvedValue(undefined),
    isRefreshing: false
  });
  vi.mocked(useSavedQueries).mockReturnValue({
    queries: [],
    isLoading: false,
    error: null,
    upsert: vi.fn(),
    remove: vi.fn()
  });
});

function workspace() {
  const client = new QueryClient({
    defaultOptions: {queries: {retry: false}}
  });
  return (
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <QueryWorkspace />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

describe('QueryWorkspace accessibility (SPEC-045 FR-003)', () => {
  it('has no axe violations with schema tables + a succeeded result set', async () => {
    await expectNoA11yViolations(workspace(), ROUTE_AXE_OPTIONS);
  });

  it('has no axe violations with the schema rail collapsed (SPEC-085 FR-004)', async () => {
    localStorage.setItem('portal.rail.collapsed', 'true');
    await expectNoA11yViolations(workspace(), ROUTE_AXE_OPTIONS);
  });

  it('exposes exactly one <h1> and a <main> landmark', async () => {
    render(workspace());
    expect(await screen.findByLabelText('SQL editor')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
    expect(screen.getByRole('main')).toBeInTheDocument();
  });
});
