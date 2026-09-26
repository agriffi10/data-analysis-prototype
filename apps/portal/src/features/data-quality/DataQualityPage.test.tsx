import {beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataQualityPage} from './DataQualityPage';
import {MemoryRouter, Route, Routes} from 'react-router';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {ROUTE_AXE_OPTIONS, expectContainerHasNoA11yViolations, expectNoA11yViolations} from '../../test/axe';
import {ToastProvider} from '../../components/ToastProvider';
import {AuthContext} from '../auth/authContext';
import type {DataQualityRunSummary} from './dataQuality.types';
import type {FileListPage} from '../../types/s3.types';
import type {ReactElement} from 'react';
import * as runsService from './dataQualityRuns.service';
import * as dqService from './dataQuality.service';
import * as fileBrowserService from '../file-browser/fileBrowser.service';
import * as sharedSpaces from '../shared-spaces/sharedSpaces.service';
import * as fileBrowser from '../file-browser/fileBrowser.service';

// ─── from DataQualityPage.test.tsx ───
vi.mock('./dataQualityRuns.service', async (importActual) => ({
  ...(await importActual<typeof runsService>()),
  getRunsIndex: vi.fn()
}));

vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
vi.mock('./dataQuality.service', () => ({enqueueQualityCheck: vi.fn()}));
vi.mock('../file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof fileBrowserService>()),
  listFiles: vi.fn()
}));

describe('DataQualityPage', () => {
  // Integration style (react.md §21): the real page, the real useDataQualityRuns, the real
  // useConnections — mocking only the AWS service boundaries they sit on.

  const mockIndex = vi.mocked(runsService.getRunsIndex);
  const mockCache = vi.mocked(sharedSpaces.readSharedConnectionsCache);
  const mockEnqueue = vi.mocked(dqService.enqueueQualityCheck);
  const mockList = vi.mocked(fileBrowserService.listFiles);

  const page = (over: Partial<FileListPage> = {}): FileListPage => ({
    files: [],
    folders: [],
    isTruncated: false,
    ...over
  });

  function run(over: Partial<DataQualityRunSummary> = {}): DataQualityRunSummary {
    return {
      requestId: 'r-1',
      space: 'alice',
      location: 'alice/sales/',
      format: 'csv',
      verdict: 'issues_found',
      fileCount: 3,
      hasApproximateFigures: false,
      timestamp: '2026-07-20T10:00:00Z',
      ...over
    };
  }

  const ok = (runs: DataQualityRunSummary[]) => ({success: true as const, data: runs});

  /**
   * Find a row by its location.
   *
   * The location renders as TWO spans (a truncatable parent + the identifying final
   * segment), so `getByText('alice/sales/')` would not match a single node. The link's
   * accessible name carries the whole location, which is the thing a user actually
   * navigates by — so asserting on it tests the row's contract rather than its markup.
   */
  const rowFor = (location: string) => screen.findByRole('link', {name: new RegExp(escapeRe(location))});
  const rowForSync = (location: string) => screen.getByRole('link', {name: new RegExp(escapeRe(location))});
  const escapeRe = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const failed = {success: false as const, error: {message: 'nope', code: 'AccessDenied'}};

  function renderPage() {
    return renderWithProviders(<DataQualityPage />, {route: '/data-quality', auth: authenticated('alice')});
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
    vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
    window.innerWidth = 1024;
    mockCache.mockResolvedValue({
      success: true,
      data: {version: 1, connections: [{name: 'team-data', role: 'member', status: 'active'}]}
    });
    mockIndex.mockResolvedValue(ok([]));
    mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'req-1'}});
    mockList.mockResolvedValue({success: true, data: page()});
  });

  describe('DataQualityPage — the list', () => {
    it('lists checks newest first across the personal and shared spaces', async () => {
      mockIndex.mockImplementation(async (_bucket, space) =>
        space === 'alice'
          ? ok([run({requestId: 'p-old', timestamp: '2026-07-01T10:00:00Z'})])
          : ok([
              run({
                requestId: 's-new',
                space: 'team-data',
                location: 'team-data/raw/',
                timestamp: '2026-07-20T10:00:00Z'
              })
            ])
      );

      renderPage();

      const rows = await screen.findAllByRole('listitem');
      expect(rows).toHaveLength(2);
      // Newest first — and the shared-space run IS the newest, so this also proves the
      // merge happens before the sort rather than per-space.
      expect(rows[0]).toHaveTextContent('team-data/raw/');
      expect(rows[1]).toHaveTextContent('alice/sales/');
    });

    it('names the location in the link, never "view" or "here"', async () => {
      mockIndex.mockImplementation(async (_bucket, space) => (space === 'alice' ? ok([run()]) : ok([])));
      renderPage();

      const link = await screen.findByRole('link', {name: /alice\/sales\//});
      expect(link).toBeInTheDocument();
      expect(screen.queryByRole('link', {name: /^(view|here)$/i})).not.toBeInTheDocument();
    });

    it('still renders the readable spaces when one space cannot be read', async () => {
      // FR-002: one unreadable space must never blank the whole page.
      mockIndex.mockImplementation(async (_bucket, space) => (space === 'alice' ? ok([run()]) : failed));

      renderPage();

      expect(await rowFor('alice/sales/')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });

  describe('DataQualityPage — the verdict and the sampled qualifier', () => {
    it('never renders a sampled run as an unqualified Clean', async () => {
      // The list is where a user forms a quick impression, so the same rule SPEC-112 and
      // SPEC-114 enforce in the report and the notification applies at row level too.
      mockIndex.mockImplementation(async (_bucket, space) =>
        space === 'alice' ? ok([run({verdict: 'clean', hasApproximateFigures: true})]) : ok([])
      );

      renderPage();

      const row = (await screen.findAllByRole('listitem'))[0];
      expect(within(row).getByText('Clean')).toBeInTheDocument();
      expect(within(row).getByText('Sampled')).toBeInTheDocument();
      // The link's name replaces what the row shows, so it must not drop the qualifier either.
      expect(within(row).getByRole('link')).toHaveAccessibleName(/— clean, sampled$/);
    });

    it('omits the sampled chip when nothing was estimated', async () => {
      mockIndex.mockImplementation(async (_bucket, space) =>
        space === 'alice' ? ok([run({verdict: 'clean', hasApproximateFigures: false})]) : ok([])
      );
      renderPage();
      expect(await screen.findByText('Clean')).toBeInTheDocument();
      expect(screen.queryByText('Sampled')).not.toBeInTheDocument();
    });
  });

  describe('DataQualityPage — filtering and paging', () => {
    const many = (n: number, verdict: DataQualityRunSummary['verdict'] = 'issues_found') =>
      Array.from({length: n}, (_, i) =>
        run({
          requestId: `r-${i}`,
          location: `alice/f${i}/`,
          verdict,
          timestamp: `2026-07-${String(20 - i).padStart(2, '0')}T10:00:00Z`
        })
      );

    it('pages 10 at a time and labels the range', async () => {
      mockIndex.mockImplementation(async (_bucket, space) => (space === 'alice' ? ok(many(12)) : ok([])));
      const {user} = renderPage();

      await rowFor('alice/f0/');
      expect(screen.getAllByRole('listitem')).toHaveLength(10);
      expect(screen.getByText(/1–10 of 12/)).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: /next/i}));
      expect(screen.getAllByRole('listitem')).toHaveLength(2);
      expect(screen.getByText(/11–12 of 12/)).toBeInTheDocument();
    });

    it('filters by verdict and resets to the first page', async () => {
      mockIndex.mockImplementation(async (_bucket, space) =>
        space === 'alice'
          ? ok([...many(11), run({requestId: 'clean-1', location: 'alice/ok/', verdict: 'clean'})])
          : ok([])
      );
      const {user} = renderPage();

      await rowFor('alice/f0/');
      await user.click(screen.getByRole('button', {name: /next/i}));
      expect(screen.getByText(/11–12 of 12/)).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'Clean'}));
      expect(screen.getByText(/1–1 of 1/)).toBeInTheDocument();
      expect(rowForSync('alice/ok/')).toBeInTheDocument();
    });
  });

  describe('DataQualityPage — empty, loading and error states', () => {
    it('offers to start one right here when nothing has ever run', async () => {
      // SPEC-124 FR-001 amends SPEC-123 FR-005: the empty state used to send the user to the
      // Files browser. It now offers the action on the page that can do the job.
      renderPage();
      expect(await screen.findByText('No quality checks yet')).toBeInTheDocument();
      expect(screen.getAllByRole('button', {name: 'New quality check'})).toHaveLength(2);
      expect(screen.queryByText(/from any file or folder in Files/)).not.toBeInTheDocument();
    });

    it('distinguishes an empty filter from an empty history', async () => {
      // Otherwise the user thinks their history vanished.
      mockIndex.mockImplementation(async (_bucket, space) =>
        space === 'alice' ? ok([run({verdict: 'issues_found'})]) : ok([])
      );
      const {user} = renderPage();

      await rowFor('alice/sales/');
      await user.click(screen.getByRole('button', {name: 'Clean'}));

      expect(screen.getByText('No checks match this filter')).toBeInTheDocument();
      expect(screen.queryByText('No quality checks yet')).not.toBeInTheDocument();
    });

    it('shows a friendly banner with Try again when every space fails', async () => {
      mockIndex.mockResolvedValue(failed);
      renderPage();

      const alert = await screen.findByRole('alert');
      expect(within(alert).getByRole('button', {name: /try again/i})).toBeInTheDocument();
      // SPEC-106: never the raw service message.
      expect(alert).not.toHaveTextContent('nope');
    });

    it('refetches when Try again is clicked', async () => {
      mockIndex.mockResolvedValue(failed);
      const {user} = renderPage();

      await screen.findByRole('alert');
      mockIndex.mockImplementation(async (_bucket, space) => (space === 'alice' ? ok([run()]) : ok([])));
      await user.click(screen.getByRole('button', {name: /try again/i}));

      expect(await rowFor('alice/sales/')).toBeInTheDocument();
    });
  });

  describe('DataQualityPage — the completed-only signpost', () => {
    it('says failed checks report themselves in notifications, and links there', async () => {
      // A history page that silently omits failures teaches the user to trust a list that
      // is lying to them by omission. This line is what converts the omission into a
      // signpost, so its absence is a real regression, not a copy nit.
      renderPage();

      const link = await screen.findByRole('link', {name: 'notifications'});
      expect(link).toHaveAttribute('href', '/notifications');
      expect(screen.getByText(/This lists checks that finished/)).toBeInTheDocument();
    });
  });

  // SPEC-124: the dashboard as a second entry point into a check.
  describe('DataQualityPage — starting a check (SPEC-124)', () => {
    const openDialog = async (user: ReturnType<typeof renderPage>['user']) => {
      const triggers = await screen.findAllByRole('button', {name: 'New quality check'});
      await user.click(triggers[0]);
      return screen.findByRole('dialog', {name: 'Start a quality check'});
    };

    it('offers the action even when the history cannot be read', async () => {
      // Starting a check must never depend on the list being readable — the two are
      // unrelated S3 reads, and the failure the user can act on is the one they came for.
      mockIndex.mockResolvedValue(failed);
      renderPage();

      await screen.findByRole('alert');
      expect(screen.getByRole('button', {name: 'New quality check'})).toBeEnabled();
    });

    it('enqueues the browsed folder and confirms with a banner, not a toast', async () => {
      mockList.mockResolvedValue({
        success: true,
        data: page({folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}]})
      });
      const {user} = renderPage();

      await openDialog(user);
      await user.click(await screen.findByRole('button', {name: /open folder sales/i}));
      await user.click(await screen.findByRole('button', {name: 'Check this folder'}));

      await waitFor(() =>
        expect(mockEnqueue).toHaveBeenCalledWith(
          expect.objectContaining({
            space: {kind: 'personal', bucket: 'user-space', prefix: 'alice/'},
            location: 'alice/sales/'
          })
        )
      );

      // The banner is the receipt; a toast as well would be two confirmations for one action.
      const banner = await screen.findByText(/It will appear in this list when it finishes/);
      expect(banner).toBeInTheDocument();
      expect(screen.queryByText(/you’ll get a notification when it finishes\./)).not.toBeInTheDocument();
      // It reports that the check STARTED and claims nothing about the result.
      expect(banner).not.toHaveTextContent(/passed|clean|no issues/i);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('keeps the dialog open with the target intact when the enqueue fails', async () => {
      mockEnqueue.mockResolvedValue({success: false, error: {message: 'raw aws text', code: 'AccessDenied'}});
      mockList.mockResolvedValue({
        success: true,
        data: page({folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}]})
      });
      const {user} = renderPage();

      await openDialog(user);
      await user.click(await screen.findByRole('button', {name: /open folder sales/i}));
      await user.click(await screen.findByRole('button', {name: 'Check this folder'}));

      // Failure is announced by the hook (SPEC-106 wording), never by echoing AWS.
      await waitFor(() => expect(screen.getByText(/don't have permission/i)).toBeInTheDocument());
      expect(screen.queryByText('raw aws text')).not.toBeInTheDocument();
      // The dialog survives, still browsed to the folder the user picked.
      expect(screen.getByRole('dialog', {name: 'Start a quality check'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Check this folder'})).toBeInTheDocument();
      expect(screen.queryByText(/It will appear in this list when it finishes/)).not.toBeInTheDocument();
    });

    it('resets the picker when the space changes, so a selection cannot straddle spaces', async () => {
      mockList.mockImplementation(async (bucket) =>
        bucket === 'user-space'
          ? {
              success: true,
              data: page({
                files: [{type: 'file', key: 'alice/mine.csv', name: 'mine.csv', size: 1, lastModified: new Date(0)}]
              })
            }
          : {
              success: true,
              data: page({
                files: [
                  {type: 'file', key: 'team-data/theirs.csv', name: 'theirs.csv', size: 1, lastModified: new Date(0)}
                ]
              })
            }
      );
      const {user} = renderPage();

      await openDialog(user);
      await user.click(await screen.findByRole('button', {name: 'Select file mine.csv'}));
      expect(screen.getByRole('button', {name: 'Check this file'})).toBeInTheDocument();

      await user.selectOptions(screen.getByLabelText('Space'), 'team-data');

      // The file target did not survive the switch — the confirm names a folder again.
      expect(await screen.findByRole('button', {name: 'Select file theirs.csv'})).toHaveAttribute(
        'aria-pressed',
        'false'
      );
      expect(screen.getByRole('button', {name: 'Check this folder'})).toBeInTheDocument();
      expect(screen.queryByText('mine.csv')).not.toBeInTheDocument();
    });

    it('never offers the reports folder or the app-managed folders as a target', async () => {
      mockList.mockResolvedValue({
        success: true,
        data: page({
          folders: [
            {type: 'folder', prefix: 'alice/_data-quality-reports/', name: '_data-quality-reports'},
            {type: 'folder', prefix: 'alice/system_settings/athenaresults/', name: 'athenaresults'},
            {type: 'folder', prefix: 'alice/user_settings/', name: 'user_settings'},
            {type: 'folder', prefix: 'alice/sales/', name: 'sales'}
          ]
        })
      });
      const {user} = renderPage();

      await openDialog(user);
      expect(await screen.findByRole('button', {name: /open folder sales/i})).toBeInTheDocument();
      for (const hidden of ['_data-quality-reports', 'athenaresults', 'user_settings']) {
        expect(screen.queryByRole('button', {name: `Open folder ${hidden}`})).not.toBeInTheDocument();
      }
    });
  });
});

// ─── from DataQualityPage.a11y.test.tsx ───

describe('DataQualityPage.a11y', () => {
  const mockIndex = vi.mocked(runsService.getRunsIndex);
  const mockCache = vi.mocked(sharedSpaces.readSharedConnectionsCache);

  // A local provider stack with default gcTime (not renderWithProviders'): the cache warmed
  // by the first `render` is reused by the render inside expectNoA11yViolations, so axe sees
  // the populated list rather than the loading line (the NotificationsPage.a11y precedent).
  // Bespoke tree AND bespoke client, both deliberate (SPEC-154 FR-007):
  // `expectNoA11yViolations` takes a COMPOSED ELEMENT, and the default `gcTime` is what
  // the warm-cache note below depends on — `createTestQueryClient`'s `gcTime: 0` would
  // leave the second render cold and axe would inspect a loading state.
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
    // A folder AND a file, so the start-a-check dialog's selectable file row is in the
    // tree axe sees. The suite-wide `listFiles` mock is bare `vi.fn()`.
    vi.mocked(fileBrowser.listFiles).mockResolvedValue({
      success: true,
      data: {
        folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}],
        files: [{type: 'file', key: 'alice/report.csv', name: 'report.csv', size: 1, lastModified: new Date(0)}],
        isTruncated: false
      }
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
      await userEvent.setup(USER_EVENT_OPTIONS).click(screen.getAllByRole('button', {name: 'New quality check'})[0]);
      await screen.findByRole('button', {name: 'Select file report.csv'});

      await expectContainerHasNoA11yViolations(container, ROUTE_AXE_OPTIONS);
    });
  });
});
