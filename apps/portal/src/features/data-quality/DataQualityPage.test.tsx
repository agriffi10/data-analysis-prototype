import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, within, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataQualityPage} from './DataQualityPage';
import * as runsService from './dataQualityRuns.service';
import * as dqService from './dataQuality.service';
import * as fileBrowserService from '../file-browser/fileBrowser.service';
import * as sharedSpaces from '../shared-spaces/sharedSpaces.service';
import type {DataQualityRunSummary} from './dataQuality.types';
import type {FileListPage} from '../../types/s3.types';

// Integration style (react.md §21): the real page, the real useDataQualityRuns, the real
// useConnections — mocking only the AWS service boundaries they sit on.
vi.mock('./dataQualityRuns.service', async (importActual) => ({
  ...(await importActual<typeof runsService>()),
  getRunsIndex: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({readSharedConnectionsCache: vi.fn()}));
vi.mock('./dataQuality.service', () => ({enqueueQualityCheck: vi.fn()}));
vi.mock('../file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof fileBrowserService>()),
  listFiles: vi.fn()
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}}),
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'tok'})
}));

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
const queryRowFor = (location: string) => screen.queryByRole('link', {name: new RegExp(escapeRe(location))});
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
            run({requestId: 's-new', space: 'team-data', location: 'team-data/raw/', timestamp: '2026-07-20T10:00:00Z'})
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

  it('links each row to its report, carrying the space it came from', async () => {
    mockIndex.mockImplementation(async (_bucket, space) =>
      space === 'team-data' ? ok([run({requestId: 'r-9', space: 'team-data', location: 'team-data/raw/'})]) : ok([])
    );

    renderPage();

    const link = await screen.findByRole('link', {name: /team-data\/raw\//});
    expect(link).toHaveAttribute('href', '/data-quality/team-data/r-9');
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
  it('shows the verdict as a dot PLUS a label, never colour alone', async () => {
    mockIndex.mockImplementation(async (_bucket, space) =>
      space === 'alice' ? ok([run({verdict: 'clean'})]) : ok([])
    );
    renderPage();
    expect(await screen.findByText('Clean')).toBeInTheDocument();
  });

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

  it('marks the active filter with aria-pressed, not styling alone', async () => {
    mockIndex.mockImplementation(async (_bucket, space) => (space === 'alice' ? ok([run()]) : ok([])));
    const {user} = renderPage();

    await rowFor('alice/sales/');
    expect(screen.getByRole('button', {name: 'All'})).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', {name: 'Issues found'}));
    expect(screen.getByRole('button', {name: 'Issues found'})).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', {name: 'All'})).toHaveAttribute('aria-pressed', 'false');
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

  it('announces loading as a status line', async () => {
    mockIndex.mockImplementation(() => new Promise(() => {}));
    renderPage();
    expect(await screen.findByRole('status')).toHaveTextContent(/Loading data quality checks/);
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

  it('refreshes on demand', async () => {
    mockIndex.mockImplementation(async (_bucket, space) => (space === 'alice' ? ok([run()]) : ok([])));
    const {user} = renderPage();

    await rowFor('alice/sales/');
    mockIndex.mockImplementation(async (_bucket, space) =>
      space === 'alice' ? ok([run({requestId: 'r-2', location: 'alice/new/'})]) : ok([])
    );
    await user.click(screen.getByRole('button', {name: /refresh data quality checks/i}));

    await waitFor(() => expect(queryRowFor('alice/new/')).toBeInTheDocument());
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

  it('does not promise a notification for EVERY failure while SPEC-126 is unbuilt', async () => {
    // A request that never starts an execution (DLQ) notifies nobody until SPEC-126
    // drains it. Promising otherwise would relocate the very lie this line exists to
    // prevent. Tighten this test to an absolute promise when SPEC-126 ships.
    renderPage();

    const note = await screen.findByText(/This lists checks that finished/);
    expect(note).toHaveTextContent(/usually/);
    expect(note).not.toHaveTextContent(/always/);
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

  it('enqueues a single file when one is selected', async () => {
    mockList.mockResolvedValue({
      success: true,
      data: page({
        files: [{type: 'file', key: 'alice/report.csv', name: 'report.csv', size: 1, lastModified: new Date(0)}]
      })
    });
    const {user} = renderPage();

    await openDialog(user);
    await user.click(await screen.findByRole('button', {name: 'Select file report.csv'}));
    // The confirm label names the target — the user is one click from a background job.
    await user.click(await screen.findByRole('button', {name: 'Check this file'}));

    await waitFor(() =>
      expect(mockEnqueue).toHaveBeenCalledWith(expect.objectContaining({location: 'alice/report.csv'}))
    );
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

  it('lists usable spaces only, personal first', async () => {
    mockCache.mockResolvedValue({
      success: true,
      data: {
        version: 1,
        connections: [
          {name: 'team-data', role: 'member', status: 'active'},
          {name: 'half-built', role: 'owner', status: 'provisioning'}
        ]
      }
    });
    const {user} = renderPage();

    await openDialog(user);
    const options = within(screen.getByLabelText('Space')).getAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual(['alice', 'team-data (shared)']);
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
          {type: 'folder', prefix: 'alice/athenaresults/', name: 'athenaresults'},
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

  it('returns focus to the trigger when the dialog is dismissed', async () => {
    const {user} = renderPage();

    const trigger = (await screen.findAllByRole('button', {name: 'New quality check'}))[0];
    await user.click(trigger);
    await screen.findByRole('dialog', {name: 'Start a quality check'});
    await user.click(screen.getByRole('button', {name: /cancel/i}));

    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
