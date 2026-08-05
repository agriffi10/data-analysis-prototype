import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, waitFor, cleanup, fireEvent} from '@testing-library/react';
import {MemoryRouter, Routes, Route} from 'react-router';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactElement} from 'react';
import {expectNoA11yViolations, expectContainerHasNoA11yViolations, ROUTE_AXE_OPTIONS} from '../../test/axe';
import {ToastProvider} from '../../components/ToastProvider';
import {AuthContext} from '../auth/authContext';
import {authenticated} from '../../test/authFixtures';
import {DataQualityPage} from './DataQualityPage';
import * as runsService from './dataQualityRuns.service';
import * as fileBrowser from '../file-browser/fileBrowser.service';
import * as sharedSpaces from '../shared-spaces/sharedSpaces.service';
import type {DataQualityRunSummary} from './dataQuality.types';

vi.mock('./dataQualityRuns.service', async (importActual) => ({
  ...(await importActual<typeof runsService>()),
  getRunsIndex: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({readSharedConnectionsCache: vi.fn()}));
vi.mock('../file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof fileBrowser>()),
  listFiles: vi.fn().mockResolvedValue({
    success: true,
    data: {
      folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}],
      files: [{type: 'file', key: 'alice/report.csv', name: 'report.csv', size: 1, lastModified: new Date(0)}],
      isTruncated: false
    }
  })
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}}),
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'tok'})
}));

const mockIndex = vi.mocked(runsService.getRunsIndex);
const mockCache = vi.mocked(sharedSpaces.readSharedConnectionsCache);

// A local provider stack with default gcTime (not renderWithProviders'): the cache warmed
// by the first `render` is reused by the render inside expectNoA11yViolations, so axe sees
// the populated list rather than the loading line (the NotificationsPage.a11y precedent).
const client = new QueryClient({defaultOptions: {queries: {retry: false}}});

function withProviders(): ReactElement {
  return (
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={authenticated('alice')}>
        <MemoryRouter initialEntries={['/data-quality']}>
          <ToastProvider>
            <Routes>
              <Route
                path="/data-quality"
                element={<DataQualityPage />}
              />
            </Routes>
          </ToastProvider>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  );
}

function run(over: Partial<DataQualityRunSummary> = {}): DataQualityRunSummary {
  return {
    requestId: 'r-1',
    space: 'alice',
    location: 'alice/sales/',
    format: 'csv',
    verdict: 'issues_found',
    fileCount: 3,
    hasApproximateFigures: true,
    timestamp: '2026-07-20T10:00:00Z',
    ...over
  };
}

/** Render, wait for the list, unmount — then hand the same tree to axe. */
async function renderThenAxe() {
  const ui = withProviders();
  render(ui);
  await waitFor(() => expect(screen.getByRole('link', {name: /alice\/sales\//})).toBeInTheDocument());
  cleanup();
  await expectNoA11yViolations(ui, ROUTE_AXE_OPTIONS);
}

beforeEach(() => {
  vi.clearAllMocks();
  client.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  mockCache.mockResolvedValue({success: true, data: {version: 1, connections: []}});
  mockIndex.mockResolvedValue({
    success: true,
    data: [run(), run({requestId: 'r-2', verdict: 'clean', hasApproximateFigures: false, location: 'alice/ok.csv'})]
  });
});

describe('DataQualityPage a11y', () => {
  it('has no axe violations listing checks', async () => {
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

  it('has no axe violations with the start-a-check dialog open (SPEC-124)', async () => {
    // The dialog is a state the user drives into, so this renders, clicks, and checks the
    // live container — `expectNoA11yViolations` has no point between render and assert at
    // which to open it.
    const {container} = render(withProviders());
    await waitFor(() => expect(screen.getByRole('link', {name: /alice\/sales\//})).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole('button', {name: 'New quality check'})[0]);
    await screen.findByRole('button', {name: 'Select file report.csv'});

    await expectContainerHasNoA11yViolations(container, ROUTE_AXE_OPTIONS);
  });

  it('exposes exactly one h1 and one main landmark', async () => {
    render(withProviders());
    await waitFor(() => expect(screen.getByRole('link', {name: /alice\/sales\//})).toBeInTheDocument());

    expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
    expect(screen.getAllByRole('main')).toHaveLength(1);
  });
});
