import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, within, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataQualityPage} from './DataQualityPage';
import * as runsService from './dataQualityRuns.service';
import * as sharedSpaces from '../shared-spaces/sharedSpaces.service';
import type {DataQualityRunSummary} from './dataQuality.types';

// Integration style (react.md §21): the real page, the real useDataQualityRuns, the real
// useConnections — mocking only the AWS service boundaries they sit on.
vi.mock('./dataQualityRuns.service', async (importActual) => ({
  ...(await importActual<typeof runsService>()),
  getRunsIndex: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({readSharedConnectionsCache: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}}),
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'tok'})
}));

const mockIndex = vi.mocked(runsService.getRunsIndex);
const mockCache = vi.mocked(sharedSpaces.readSharedConnectionsCache);

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
  it('invites the user to start one when nothing has ever run', async () => {
    renderPage();
    expect(await screen.findByText('No quality checks yet')).toBeInTheDocument();
    expect(screen.getByText(/Start one from any file or folder in Files/)).toBeInTheDocument();
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
