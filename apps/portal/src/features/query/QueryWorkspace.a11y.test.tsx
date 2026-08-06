import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router';
import {QueryClientProvider} from '@tanstack/react-query';
import type {ReactElement} from 'react';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS} from '../../test/axe';
import {createTestQueryClient} from '../../test/renderWithProviders';
import {authValue} from '../../test/authFixtures';
import {ToastProvider} from '../../components/ToastProvider';
import {AuthContext} from '../auth/authContext';

// Integration a11y (react.md §21): render the REAL workspace — real SchemaBrowser
// over the mocked glue boundary, the real tab strip/toolbar/results shell — and
// check it under axe. Only the AWS service boundary + the heavy Monaco editor are
// mocked. The QueryClient is pre-seeded so the schema rail shows real tables at
// axe time rather than a transient loading state.
vi.mock('./SqlEditor', () => ({
  SqlEditor: ({value, onChange}: {value: string; onChange: (v: string) => void}) => (
    <textarea
      aria-label="SQL editor"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}));
vi.mock('./glue.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./glue.service')>()),
  getDatabase: vi.fn().mockResolvedValue({success: true, data: {name: 'alice'}}),
  listTables: vi.fn().mockResolvedValue({success: true, data: []})
}));
vi.mock('./query.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./query.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn()
}));
vi.mock('./queryHistory.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./queryHistory.service')>()),
  getQueryHistory: vi.fn().mockResolvedValue({success: true, data: {version: 1, entries: []}})
}));
vi.mock('./savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./savedQueries.service')>()),
  getSavedQueries: vi.fn().mockResolvedValue({success: true, data: {version: 1, queries: []}})
}));
vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn().mockResolvedValue({success: true, data: {version: 1, connections: []}})
}));
vi.mock('../table-share/tableShare.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-share/tableShare.service')>()),
  enqueueTableShare: vi.fn()
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}}),
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'id-token'})
}));

import {QueryWorkspace} from './QueryWorkspace';
import {queryKeys} from './queryKeys';

vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bucket');

/** The real workspace inside seeded providers (schema tables warm in the cache). */
function workspace(): ReactElement {
  const client = createTestQueryClient();
  client.setQueryData(queryKeys.connections('alice'), {version: 1, connections: []});
  client.setQueryData(queryKeys.schema('alice'), {
    database: {name: 'alice'},
    tables: [{name: 'sales_2026', location: 's3://b/alice/sales/', columns: [{name: 'region', type: 'string'}]}]
  });
  client.setQueryData(queryKeys.history('alice'), {version: 1, entries: []});
  client.setQueryData(queryKeys.savedQueries('alice'), {version: 1, queries: []});
  return (
    <AuthContext.Provider value={authValue()}>
      // Bespoke tree, kept deliberately (SPEC-154 FR-007): `expectNoA11yViolations` takes a // COMPOSED ELEMENT and
      renders it itself, so there is no `renderWithProviders` result to // hand it. The QueryClient is still the
      harness's, so retry behaviour cannot drift.
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
});

describe('QueryWorkspace accessibility (SPEC-045 FR-003)', () => {
  it('has no axe violations with the schema rail populated', async () => {
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
  it('has no axe violations on the mobile browse-first workspace (SPEC-100)', async () => {
    window.innerWidth = 390;
    try {
      await expectNoA11yViolations(workspace(), ROUTE_AXE_OPTIONS);
      render(workspace());
      // Still exactly one <h1> and one <main> once the editor shell is gone.
      expect(await screen.findByRole('button', {name: 'Saved'})).toBeInTheDocument();
      expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
      expect(screen.getByRole('main')).toBeInTheDocument();
    } finally {
      window.innerWidth = 1024;
    }
  });
});
