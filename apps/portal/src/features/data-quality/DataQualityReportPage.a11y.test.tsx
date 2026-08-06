import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, waitFor, cleanup} from '@testing-library/react';
import {MemoryRouter, Routes, Route} from 'react-router';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactElement} from 'react';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS} from '../../test/axe';
import {ToastProvider} from '../../components/ToastProvider';
import {AuthContext} from '../auth/authContext';
import {authenticated} from '../../test/authFixtures';
import {DataQualityReportPage} from './DataQualityReportPage';
import * as reportService from './dataQualityReport.service';
import * as sharedSpaces from '../shared-spaces/sharedSpaces.service';
import {csvReport, parquetReport} from './reportFixtures';

vi.mock('./dataQualityReport.service', async (importActual) => ({
  ...(await importActual<typeof reportService>()),
  getQualityReport: vi.fn()
}));
vi.mock('./dataQuality.service', () => ({enqueueQualityCheck: vi.fn()}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({readSharedConnectionsCache: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}}),
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'tok'})
}));

const mockReport = vi.mocked(reportService.getQualityReport);
const mockCache = vi.mocked(sharedSpaces.readSharedConnectionsCache);

// A local provider stack with default gcTime (not renderWithProviders'): the cache
// warmed by the first `render` is reused by the render inside expectNoA11yViolations,
// so axe sees the populated report rather than the loading line. The
// NotificationsPage.a11y precedent.
// Bespoke tree AND bespoke client, both deliberate (SPEC-154 FR-007):
// `expectNoA11yViolations` takes a COMPOSED ELEMENT, and the default `gcTime` is what
// the warm-cache note below depends on — `createTestQueryClient`'s `gcTime: 0` would
// leave the second render cold and axe would inspect a loading state.
const client = new QueryClient({defaultOptions: {queries: {retry: false}}});

function withProviders(): ReactElement {
  return (
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={authenticated('alice')}>
        <MemoryRouter initialEntries={['/data-quality/alice/req-1']}>
          <ToastProvider>
            <Routes>
              <Route
                path="/data-quality/:space/:requestId"
                element={<DataQualityReportPage />}
              />
            </Routes>
          </ToastProvider>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  );
}

/** Render, wait for the report, unmount — then hand the same tree to axe. */
async function renderThenAxe() {
  const ui = withProviders();
  render(ui);
  await waitFor(() => expect(screen.getByRole('button', {name: 'Open folder'})).toBeInTheDocument());
  cleanup();
  await expectNoA11yViolations(ui, ROUTE_AXE_OPTIONS);
}

beforeEach(() => {
  vi.clearAllMocks();
  client.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  mockCache.mockResolvedValue({success: true, data: {version: 1, connections: []}});
  mockReport.mockResolvedValue({success: true, data: csvReport()});
});

describe('DataQualityReportPage a11y', () => {
  it('has no axe violations rendering a report with findings', async () => {
    await renderThenAxe();
  });

  it('has no axe violations for a report full of skipped figures', async () => {
    mockReport.mockResolvedValue({success: true, data: parquetReport()});
    await renderThenAxe();
  });

  it('has no axe violations at a phone width', async () => {
    Object.defineProperty(window, 'innerWidth', {value: 400, writable: true, configurable: true});
    try {
      await renderThenAxe();
    } finally {
      Object.defineProperty(window, 'innerWidth', {value: 1024, writable: true, configurable: true});
    }
  });

  it('exposes exactly one h1 and one main landmark', async () => {
    render(withProviders());
    await waitFor(() => expect(screen.getByRole('button', {name: 'Open folder'})).toBeInTheDocument());
    expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
    expect(screen.getAllByRole('main')).toHaveLength(1);
  });
});
