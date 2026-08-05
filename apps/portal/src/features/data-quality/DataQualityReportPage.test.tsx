import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, within, waitFor} from '@testing-library/react';
import {Routes, Route} from 'react-router';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataQualityReportPage} from './DataQualityReportPage';
import * as reportService from './dataQualityReport.service';
import * as sharedSpaces from '../shared-spaces/sharedSpaces.service';
import * as dqService from './dataQuality.service';
import {
  csvReport,
  parquetReport,
  NOTE_RAGGED,
  SKIP_BINARY,
  SKIP_TYPE_PARQUET,
  NOT_COMPUTED_DUPLICATES
} from './reportFixtures';
import type {DataQualityReport} from './dataQuality.types';

// Integration style (react.md §21): the real page, the real useDataQualityReport,
// the real useConnections — mocking only the three AWS service boundaries they sit on.
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
const mockEnqueue = vi.mocked(dqService.enqueueQualityCheck);

const navigateSpy = vi.fn();
vi.mock('react-router', async (importActual) => {
  const actual = await importActual<typeof import('react-router')>();
  return {...actual, useNavigate: () => navigateSpy};
});

/** Renders the page at a real route so `useParams` resolves as it does in the app. */
function renderReport(path: string) {
  return renderWithProviders(
    <Routes>
      <Route
        path="/data-quality/:space/:requestId"
        element={<DataQualityReportPage />}
      />
    </Routes>,
    {route: path, auth: authenticated('alice')}
  );
}

const ok = (report: DataQualityReport) => ({success: true as const, data: report});
const notFound = {
  success: false as const,
  error: {message: 'That report could not be found.', code: 'DataQualityReportNotFound'}
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  window.innerWidth = 1024;
  mockCache.mockResolvedValue({
    success: true,
    data: {version: 1, connections: [{name: 'team-data', role: 'member', status: 'active'}]}
  });
  mockReport.mockResolvedValue(ok(csvReport()));
  mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'req-new'}});
});

describe('DataQualityReportPage — rendering a report', () => {
  it('shows the verdict, the location, the summary figures and the findings', async () => {
    renderReport('/data-quality/alice/req-1');

    // Await the location: the h1 renders while the report is still loading, so
    // asserting on it first would let every sync assertion below race the fetch.
    expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
    expect(screen.getByRole('heading', {level: 1, name: 'Data quality report'})).toBeInTheDocument();
    expect(screen.getByText('Issues found')).toBeInTheDocument();
    expect(screen.getByText('1,240,000')).toBeInTheDocument(); // rows
    expect(screen.getByText('12')).toBeInTheDocument(); // duplicate rows
    // The per-column finding, with its off-type count and its offending samples.
    expect(screen.getByText('amount')).toBeInTheDocument();
    expect(screen.getByText('412')).toBeInTheDocument();
    expect(screen.getByText(/N\/A, -, 1,024/)).toBeInTheDocument();
    // The metadata footer's promise.
    expect(screen.getByText(/nothing was modified, moved, or deleted/i)).toBeInTheDocument();
  });

  it('reads a SHARED-space report straight from its URL', async () => {
    // The whole reason the space is a route param: `req-1` alone cannot say which
    // space holds the report, so a shared-space deep link would be unresolvable.
    renderReport('/data-quality/team-data/req-1');

    await waitFor(() => expect(mockReport).toHaveBeenCalled());
    expect(mockReport).toHaveBeenCalledWith('shared-space', 'team-data', 'req-1');
    expect(await screen.findByRole('heading', {level: 1, name: 'Data quality report'})).toBeInTheDocument();
  });

  it('resolves the actor’s own username as PERSONAL even when a shared space shares the name', async () => {
    // Precedence, pinned: username first, shared names only when the segment differs.
    // Without it a user would read from the shared bucket at their own prefix.
    mockCache.mockResolvedValue({
      success: true,
      data: {version: 1, connections: [{name: 'alice', role: 'member', status: 'active'}]}
    });
    renderReport('/data-quality/alice/req-1');

    await waitFor(() => expect(mockReport).toHaveBeenCalled());
    expect(mockReport).toHaveBeenCalledWith('user-space', 'alice', 'req-1');
  });
});

describe('DataQualityReportPage — qualifying what it shows', () => {
  it('never renders an approximate figure without its qualifier', async () => {
    renderReport('/data-quality/alice/req-1');

    // The ragged count, its Approximate chip, and BOTH over-counting causes.
    const raggedCount = await screen.findByText('37');
    const raggedBlock = raggedCount.closest('div.rounded-lg') as HTMLElement;
    expect(within(raggedBlock).getByText('Approximate')).toBeInTheDocument();
    expect(within(raggedBlock).getByText(new RegExp(NOTE_RAGGED.slice(0, 40)))).toBeInTheDocument();
    expect(raggedBlock).toHaveTextContent(/commas inside quotes/i);
    expect(raggedBlock).toHaveTextContent(/newlines inside quoted fields/i);

    // The encoding figure, its Sampled chip, and the coverage percentage.
    const encodingBlock = screen.getByText('Invalid text encoding').closest('div.rounded-lg') as HTMLElement;
    expect(within(encodingBlock).getByText('Sampled')).toBeInTheDocument();
    expect(encodingBlock).toHaveTextContent(/12\.5% of bytes examined/);
  });

  it('shows a Parquet report no green result it did not earn', async () => {
    mockReport.mockResolvedValue(ok(parquetReport()));
    renderReport('/data-quality/alice/req-parquet');

    // The verdict is `clean`, but checks were skipped — so the banner says so rather
    // than reading as an unqualified pass.
    expect(await screen.findByText('No issues found in what could be checked')).toBeInTheDocument();
    expect(screen.queryByText('No issues found')).not.toBeInTheDocument();
    expect(screen.getByText(/some checks couldn’t be completed/i)).toBeInTheDocument();

    // Every skipped figure carries its reason and a Skipped chip. Matched on the
    // SUBSTANCE of each reason, not the exact string: the view sentence-cases these
    // Lambda-authored fragments for display (`asSentence`), and pinning the casing here
    // would make this test fail for a presentation change it does not care about.
    expect(screen.getAllByText('Skipped').length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText(new RegExp(SKIP_TYPE_PARQUET.slice(1))).length).toBe(2); // one per column
    expect(screen.getByText(new RegExp(SKIP_BINARY.slice(1)))).toBeInTheDocument();
    // And no column claims a dominant type it was never checked for.
    expect(screen.queryByText('BIGINT')).not.toBeInTheDocument();
    expect(screen.queryByText('DOUBLE')).not.toBeInTheDocument();
  });

  it('renders a not_computed figure with its reason, never as a zero', async () => {
    mockReport.mockResolvedValue(
      ok(
        csvReport({
          exact: {
            ...csvReport().exact,
            duplicateRows: {status: 'not_computed', reason: NOT_COMPUTED_DUPLICATES}
          },
          hasIncompleteFigures: true
        })
      )
    );
    renderReport('/data-quality/alice/req-1');

    expect(await screen.findByText('Not computed')).toBeInTheDocument();
    // The tile must not read `0`, which would say "no duplicates" about a check that
    // never produced an answer.
    const tile = screen.getByText('Duplicate rows').closest('div') as HTMLElement;
    expect(tile).not.toHaveTextContent(/^Duplicate rows0$/);
  });

  it('lists cross-file column disagreements naming the odd file out', async () => {
    mockReport.mockResolvedValue(
      ok(
        csvReport({
          exact: {
            ...csvReport().exact,
            crossFile: {
              columnsAgree: false,
              disagreements: [{file: 'alice/sales/mar.csv', missing: ['region'], extra: ['area']}]
            }
          }
        })
      )
    );
    renderReport('/data-quality/alice/req-1');

    expect(await screen.findByText('alice/sales/mar.csv')).toBeInTheDocument();
    expect(screen.getByText('region')).toBeInTheDocument();
    expect(screen.getByText('area')).toBeInTheDocument();
  });
});

describe('DataQualityReportPage — the states that are not a report', () => {
  it('renders the friendly empty state for a space the user cannot reach, and never calls S3', async () => {
    renderReport('/data-quality/someone-elses-space/req-1');

    expect(await screen.findByText('Report not available')).toBeInTheDocument();
    // The point of the criterion: no probe, so an inaccessible space and a
    // nonexistent one are indistinguishable from outside.
    expect(mockReport).not.toHaveBeenCalled();
  });

  it('renders a friendly message for a report that cannot be fetched — never a raw 404', async () => {
    mockReport.mockResolvedValue(notFound);
    renderReport('/data-quality/alice/gone');

    const banner = await screen.findByText('Report not available');
    expect(banner.closest('div')).toHaveTextContent(/may still be running, or it may have been deleted/i);
    expect(document.body).not.toHaveTextContent(/NoSuchKey|404/);
  });

  it('announces loading as a status line rather than a bare spinner', async () => {
    mockReport.mockReturnValue(new Promise(() => {}));
    renderReport('/data-quality/alice/req-1');
    expect(await screen.findByRole('status')).toHaveTextContent(/loading report/i);
  });
});

describe('DataQualityReportPage — follow-through actions', () => {
  it('re-runs the check without navigating away from the report on screen', async () => {
    const {user} = renderReport('/data-quality/alice/req-1');
    await user.click(await screen.findByRole('button', {name: 'Re-run check'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue.mock.calls[0][0]).toMatchObject({
      space: {kind: 'personal', bucket: 'user-space', prefix: 'alice/'},
      location: 'alice/sales/'
    });
    expect(navigateSpy).not.toHaveBeenCalled();
    // The report the user was reading is still there.
    expect(screen.getByText('alice/sales/')).toBeInTheDocument();
  });

  it('opens the Files browser at the report’s source folder', async () => {
    const {user} = renderReport('/data-quality/alice/req-1');
    await user.click(await screen.findByRole('button', {name: 'Open folder'}));

    // `?space=` takes the connection id — the literal 'personal', not the username.
    expect(navigateSpy).toHaveBeenCalledWith('/files?space=personal&prefix=alice%2Fsales%2F');
  });

  it('opens a FILE report at its parent folder, not at the file key', async () => {
    mockReport.mockResolvedValue(ok(csvReport({location: 'alice/sales/jan.csv'})));
    const {user} = renderReport('/data-quality/alice/req-1');
    await user.click(await screen.findByRole('button', {name: 'Open folder'}));

    expect(navigateSpy).toHaveBeenCalledWith('/files?space=personal&prefix=alice%2Fsales%2F');
  });

  it('offers no Convert to Parquet action while the converter is unshipped (SPEC-120)', async () => {
    renderReport('/data-quality/alice/req-1');
    await screen.findByRole('button', {name: 'Re-run check'});
    expect(screen.queryByRole('button', {name: /parquet/i})).not.toBeInTheDocument();
  });
});
