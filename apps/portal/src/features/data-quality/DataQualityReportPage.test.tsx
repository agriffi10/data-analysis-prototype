import {beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen, waitFor, within} from '@testing-library/react';
import {Link, MemoryRouter, Route, Routes} from 'react-router';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {
  DataQualityReportPage,
  ENCODING_EXAMPLES_NOTE,
  SAMPLES_COUNTING_NOTE,
  SAMPLES_TRUNCATION_NOTE
} from './DataQualityReportPage';
import {CHECK_AT_ROOT_REFUSAL} from './dataQuality.format';
import {
  NOTE_RAGGED,
  NOT_COMPUTED_DUPLICATES,
  SAMPLES_OMITTED_TOO_LARGE,
  SKIP_BINARY,
  SKIP_TYPE_PARQUET,
  csvReport,
  duplicateSamples,
  parquetReport
} from './reportFixtures';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {ROUTE_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {ToastProvider} from '../../components/ToastProvider';
import {AuthContext} from '../auth/authContext';
import type {DataQualityReport} from './dataQuality.types';
import type {SharedConnectionsCache} from '../shared-spaces/sharedSpaces.types';
import type {ReactElement, ReactNode} from 'react';
import {connectionKeys} from '../connections/connectionKeys';
import {dataQualityKeys} from './dataQualityKeys';
import * as reportService from './dataQualityReport.service';
import * as sharedSpaces from '../shared-spaces/sharedSpaces.service';
import * as dqService from './dataQuality.service';

// ─── from DataQualityReportPage.test.tsx ───
vi.mock('./dataQualityReport.service', async (importActual) => ({
  ...(await importActual<typeof reportService>()),
  getQualityReport: vi.fn()
}));

vi.mock('./dataQuality.service', () => ({enqueueQualityCheck: vi.fn()}));
vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
// Module scope, not inside the describe: vitest hoists `vi.mock` factories above
// everything, so a spy the factory closes over has to be reachable from there.
const navigateSpy = vi.fn();
vi.mock('react-router', async (importActual) => {
  const actual = await importActual<typeof import('react-router')>();
  return {...actual, useNavigate: () => navigateSpy};
});

describe('DataQualityReportPage', () => {
  // Integration style (react.md §21): the real page, the real useDataQualityReport,
  // the real useConnections — mocking only the three AWS service boundaries they sit on.

  const mockReport = vi.mocked(reportService.getQualityReport);
  const mockCache = vi.mocked(sharedSpaces.readSharedConnectionsCache);
  const mockEnqueue = vi.mocked(dqService.enqueueQualityCheck);

  /** Renders the page at a real route so `useParams` resolves as it does in the app. `beside` renders
   *  next to the route under the same router, standing in for the shell around it — a notification's link. */
  function renderReport(path: string, queryClient?: QueryClient, beside?: ReactNode) {
    return renderWithProviders(
      <>
        <Routes>
          <Route
            path="/data-quality/:space/:requestId"
            element={<DataQualityReportPage />}
          />
        </Routes>
        {beside}
      </>,
      {route: path, auth: authenticated('alice'), ...(queryClient && {queryClient})}
    );
  }

  /** A client already holding `list` — no shared spaces unless given — read `ageMs` ago under the app's 30s
   *  staleTime rather than the harness's 0, so whether a read is owed on mount is the test's choice. */
  function clientWithCachedList(ageMs: number, list: SharedConnectionsCache = NO_SPACES.data) {
    const client = createTestQueryClient();
    client.setQueryDefaults(connectionKeys.list('alice'), {gcTime: Infinity, staleTime: 30_000});
    client.setQueryData(connectionKeys.list('alice'), list, {
      updatedAt: Date.now() - ageMs
    });
    return client;
  }

  const TEAM_DATA = {
    success: true as const,
    data: {version: 1 as const, connections: [{name: 'team-data', role: 'member' as const, status: 'active' as const}]}
  };
  const NO_SPACES = {success: true as const, data: {version: 1 as const, connections: []}};

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

    it('opens a report in a space a fresh cached list has, without reading the list', async () => {
      // Only an absence waits: a run row links to a space the list already holds, and waiting on it
      // would put a read and a loading line in front of every one.
      renderReport('/data-quality/team-data/req-1', clientWithCachedList(0, TEAM_DATA.data));

      expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
      expect(mockReport).toHaveBeenCalledWith('shared-space', 'team-data', 'req-1');
      expect(mockCache).not.toHaveBeenCalled();
    });

    it('resolves the actor’s own username as PERSONAL even when a shared space shares the name', async () => {
      // Precedence, pinned: username first, shared names only when the segment differs.
      // Without it a user would read from the shared bucket at their own prefix. The list is cached
      // before mount because the report does not wait for it: fetched ahead of the list, the
      // username resolves personal whatever the precedence, and the key keeps that first answer.
      renderReport(
        '/data-quality/alice/req-1',
        clientWithCachedList(0, {version: 1, connections: [{name: 'alice', role: 'member', status: 'active'}]})
      );

      await waitFor(() => expect(mockReport).toHaveBeenCalled());
      expect(mockReport).toHaveBeenCalledWith('user-space', 'alice', 'req-1');
    });

    it('opens a personal report without waiting for the spaces list', async () => {
      // Only a shared space needs the list to resolve; the actor's own username never does.
      mockCache.mockReturnValue(new Promise(() => {}));
      renderReport('/data-quality/alice/req-1');

      expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
      expect(mockReport).toHaveBeenCalledWith('user-space', 'alice', 'req-1');
      expect(screen.queryByText(/loading report/i)).not.toBeInTheDocument();
    });

    it.each([
      ['a wide screen', 1024],
      ['a phone', 400]
    ])('notes the other spellings a column was merged from, beside that column only, on %s', async (_label, width) => {
      window.innerWidth = width;
      const report = csvReport();
      report.exact.columns[0] = {...report.exact.columns[0], otherSpellings: ['ORDER_ID', 'Order_Id']};
      mockReport.mockResolvedValue(ok(report));

      renderReport('/data-quality/alice/req-1');

      const note = await screen.findByText(/also spelled/i);
      expect(note).toHaveTextContent('Also spelled ORDER_ID, Order_Id in other files');
      const row = note.closest('li');
      expect(row).toHaveTextContent('order_id');
      expect(row).not.toHaveTextContent('amount');
      expect(screen.getAllByText(/also spelled/i)).toHaveLength(1);
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

    it('lists cross-file column disagreements naming the odd file out, and a CSV read out of position', async () => {
      mockReport.mockResolvedValue(
        ok(
          csvReport({
            exact: {
              ...csvReport().exact,
              crossFile: {
                columnsAgree: false,
                disagreements: [
                  {file: 'alice/sales/mar.csv', missing: ['region'], extra: ['area']},
                  {file: 'alice/sales/apr.csv', missing: [], extra: [], shifted: true}
                ]
              }
            }
          })
        )
      );
      renderReport('/data-quality/alice/req-1');

      const mar = (await screen.findByText('alice/sales/mar.csv')).closest('li') as HTMLElement;
      const apr = screen.getByText('alice/sales/apr.csv').closest('li') as HTMLElement;
      expect(within(mar).getByText('region')).toBeInTheDocument();
      expect(within(mar).getByText('area')).toBeInTheDocument();
      expect(within(mar).queryByText('don’t line up with this report’s Columns')).not.toBeInTheDocument();
      expect(within(apr).getByText('don’t line up with this report’s Columns')).toBeInTheDocument();
    });
  });

  describe('DataQualityReportPage — how many rows each file holds', () => {
    it('lists each file’s row count behind a closed disclosure, relative to the checked folder', async () => {
      mockReport.mockResolvedValue(
        ok(
          csvReport({
            exact: {
              ...csvReport().exact,
              rowCountsByFile: [
                {key: 'alice/sales/jan.csv', rows: 1200},
                {key: 'alice/sales/feb/part-1.csv', rows: 0}
              ]
            }
          })
        )
      );

      renderReport('/data-quality/alice/req-1');

      const summary = await screen.findByText('Rows in each file (2 files)');
      const disclosure = summary.closest('details') as HTMLDetailsElement;
      // Closed: a folder of two hundred files would otherwise push every finding below the fold.
      expect(disclosure.open).toBe(false);

      disclosure.open = true;
      const rows = within(disclosure).getAllByRole('row').slice(1);
      expect(rows[0]).toHaveTextContent('jan.csv');
      expect(rows[0]).toHaveTextContent('1,200');
      // Relative to the folder, and a nested key keeps the segments that distinguish it.
      expect(rows[1]).toHaveTextContent('feb/part-1.csv');
      expect(rows[1]).toHaveTextContent('0');
    });

    it.each([
      ['one entry, whose count IS the report’s row count', [{key: 'alice/sales/jan.csv', rows: 1200}]],
      ['no entries at all', [] as {key: string; rows: number}[]]
    ])('shows no disclosure for %s', async (_label, rowCountsByFile) => {
      mockReport.mockResolvedValue(ok(csvReport({exact: {...csvReport().exact, rowCountsByFile}})));

      renderReport('/data-quality/alice/req-1');

      expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
      expect(screen.queryByText(/rows in each file/i)).not.toBeInTheDocument();
    });
  });

  describe('DataQualityReportPage — where the invalid text encoding is', () => {
    it('names the file and byte offset of each example, and says they are not all of them', async () => {
      mockReport.mockResolvedValue(
        ok(
          csvReport({
            approximate: {
              ...csvReport().approximate,
              encoding: {
                invalidUtf8Sequences: 12,
                sampleOffsets: [{key: 'alice/sales/jan.csv', offset: 4102}],
                coverage: 'sampled',
                coveragePercent: 12.5,
                note: 'Sampled — 12.5% of bytes examined.'
              }
            }
          })
        )
      );

      renderReport('/data-quality/alice/req-1');

      expect(await screen.findByText('jan.csv, byte 4,102')).toBeInTheDocument();
      expect(screen.getByText(ENCODING_EXAMPLES_NOTE)).toBeInTheDocument();
    });

    it('spells the example relative to the folder holding a single checked FILE', async () => {
      // `sourceFolderPrefix` reduces a file location to its parent, so the label is the
      // file's own name rather than the whole key or a blank.
      mockReport.mockResolvedValue(
        ok(
          csvReport({
            location: 'alice/sales/jan.csv',
            fileCount: 1,
            approximate: {
              ...csvReport().approximate,
              encoding: {
                invalidUtf8Sequences: 12,
                sampleOffsets: [{key: 'alice/sales/jan.csv', offset: 4102}],
                coverage: 'complete',
                coveragePercent: 100,
                note: 'Complete — every byte examined.'
              }
            }
          })
        )
      );

      renderReport('/data-quality/alice/req-1');

      expect(await screen.findByText('jan.csv, byte 4,102')).toBeInTheDocument();
    });

    it('shows no examples when the scan found no invalid sequences', async () => {
      mockReport.mockResolvedValue(
        ok(
          csvReport({
            approximate: {
              ...csvReport().approximate,
              encoding: {
                invalidUtf8Sequences: 0,
                sampleOffsets: [],
                coverage: 'complete',
                coveragePercent: 100,
                note: 'Complete — every byte examined.'
              }
            }
          })
        )
      );

      renderReport('/data-quality/alice/req-1');

      expect(await screen.findByText('Complete — every byte examined.')).toBeInTheDocument();
      expect(screen.queryByText(ENCODING_EXAMPLES_NOTE)).not.toBeInTheDocument();
      expect(screen.queryByText(/, byte /)).not.toBeInTheDocument();
    });
  });

  describe('DataQualityReportPage — which rows repeat', () => {
    /** A report carrying whatever `duplicateSamples` the case under test needs. */
    function withSamples(samples: DataQualityReport['exact']['duplicateSamples']) {
      return csvReport({exact: {...csvReport().exact, duplicateSamples: samples}});
    }

    it('heads each sampled row with the columns it was grouped by, and says what the counts mean', async () => {
      mockReport.mockResolvedValue(ok(withSamples(duplicateSamples())));

      renderReport('/data-quality/alice/req-1');

      const table = await screen.findByRole('table', {name: 'Most repeated rows'});
      const [header, first] = within(table).getAllByRole('row');
      expect(
        within(header)
          .getAllByRole('columnheader')
          .map((cell) => cell.textContent)
      ).toEqual(['Times it appears', 'name', 'city']);
      expect(
        within(first)
          .getAllByRole('cell')
          .map((cell) => cell.textContent)
      ).toEqual(['3', 'a', 'x']);
      // Both notes: one so the tile's figure and these counts are not read as the same
      // number, one so a value ending in an ellipsis is not read as the data.
      expect(screen.getByText(SAMPLES_COUNTING_NOTE)).toBeInTheDocument();
      expect(screen.getByText(SAMPLES_TRUNCATION_NOTE)).toBeInTheDocument();
    });

    it('tells a NULL cell apart from an empty one, as the Data Explorer does', async () => {
      // Two different findings — a missing field and a field someone wrote nothing into — and
      // rendering either as a blank cell would collapse them into the same thing.
      mockReport.mockResolvedValue(ok(withSamples(duplicateSamples())));

      renderReport('/data-quality/alice/req-1');

      const table = await screen.findByRole('table', {name: 'Most repeated rows'});
      const second = within(table).getAllByRole('row')[2];
      expect(
        within(second)
          .getAllByRole('cell')
          .map((cell) => cell.textContent)
      ).toEqual(['2', 'NULL', '(empty)']);
    });

    it('shows the sentence instead of a table when the samples were left out', async () => {
      mockReport.mockResolvedValue(ok(withSamples({omitted: SAMPLES_OMITTED_TOO_LARGE})));

      renderReport('/data-quality/alice/req-1');

      expect(await screen.findByRole('heading', {name: 'Most repeated rows'})).toBeInTheDocument();
      expect(screen.getByText(new RegExp(SAMPLES_OMITTED_TOO_LARGE.slice(4, 60)))).toBeInTheDocument();
      expect(screen.queryByRole('table', {name: 'Most repeated rows'})).not.toBeInTheDocument();
    });

    it.each([
      ['a report written before the samples existed', undefined],
      ['a report whose statement returned none', {columns: ['name', 'city'], rows: []}]
    ])('shows no section at all for %s', async (_label, samples) => {
      mockReport.mockResolvedValue(ok(withSamples(samples as DataQualityReport['exact']['duplicateSamples'])));

      renderReport('/data-quality/alice/req-1');

      // The duplicate figure is still there — only the elaboration is absent.
      expect(await screen.findByText('12')).toBeInTheDocument();
      expect(screen.queryByText('Most repeated rows')).not.toBeInTheDocument();
    });
  });

  describe('DataQualityReportPage — a column named after a partition', () => {
    it('says a CSV column kept its values under a new name and a left-out one has no figures, and says nothing on an older report', async () => {
      mockReport.mockResolvedValue(
        ok(
          csvReport({
            partitionNamedColumns: [
              {name: 'Year', outcome: 'renamed', as: 'year_in_file'},
              {name: 'Month', outcome: 'omitted'}
            ]
          })
        )
      );
      renderReport('/data-quality/alice/req-1');

      const columns = (await screen.findByRole('heading', {name: 'Columns'})).closest('section') as HTMLElement;
      const renamed = within(columns).getByText('Year').closest('li') as HTMLElement;
      const omitted = within(columns).getByText('Month').closest('li') as HTMLElement;
      expect(renamed).toHaveTextContent(
        'Year is listed as year_in_file. The folder has a partition of the same name, and a CSV’s columns are read in order, so the file’s own column keeps its values under a new name.'
      );
      expect(omitted).toHaveTextContent(
        'Month has no figures here. The folder has a partition of the same name, and a table over this folder reads the partition’s value in its place.'
      );

      cleanup();
      mockReport.mockResolvedValue(ok(csvReport()));
      renderReport('/data-quality/alice/req-1');

      const plain = (await screen.findByRole('heading', {name: 'Columns'})).closest('section') as HTMLElement;
      expect(within(plain).queryByText(/partition of the same name/)).not.toBeInTheDocument();
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

    it.each([
      ['a fresh cached list predates the space', () => clientWithCachedList(0)],
      ['a stale cached list predates the space', () => clientWithCachedList(60_000)]
    ])('reads the spaces list before refusing a space it lacks (%s)', async (_cached, seededClient) => {
      // A completion notification followed in a second tab, whose list was read before the user joined
      // the space: trusted, the list refused a report the user can read. Fresh, nothing read it again and
      // the refusal stood; stale, "Report not available" showed until the read owed on mount returned.
      let resolveRead: (result: typeof TEAM_DATA) => void = () => {};
      mockCache.mockReturnValue(new Promise((resolve) => (resolveRead = resolve)));
      renderReport('/data-quality/team-data/req-1', seededClient());

      expect(await screen.findByText(/loading report/i)).toBeInTheDocument();
      expect(screen.queryByText('Report not available')).not.toBeInTheDocument();
      expect(mockCache).toHaveBeenCalledOnce();
      expect(mockReport).not.toHaveBeenCalled();

      resolveRead(TEAM_DATA);
      expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
      expect(mockReport).toHaveBeenCalledWith('shared-space', 'team-data', 'req-1');
    });

    it('refuses a space still missing after that read, on one read and without calling S3', async () => {
      mockCache.mockResolvedValue(NO_SPACES);
      renderReport('/data-quality/team-data/req-1', clientWithCachedList(0));

      expect(await screen.findByText('Report not available')).toBeInTheDocument();
      expect(mockCache).toHaveBeenCalledOnce();
      expect(mockReport).not.toHaveBeenCalled();
    });

    it('keeps a loaded report off the page once a later read of the list withdraws its space', async () => {
      // The disabled query keeps its data, so without the gate the refusal and the report showed together —
      // and a link back to the report, waiting on its read, showed the loading line over the report.
      const {user, queryClient} = renderReport(
        '/data-quality/team-data/req-1',
        clientWithCachedList(0, TEAM_DATA.data),
        <Link to="/data-quality/team-data/req-1">Open the team-data report</Link>
      );
      expect(await screen.findByText('alice/sales/')).toBeInTheDocument();

      mockCache.mockResolvedValue(NO_SPACES);
      await queryClient.invalidateQueries({queryKey: connectionKeys.list('alice')});

      expect(await screen.findByText('Report not available')).toBeInTheDocument();
      expect(screen.queryByText('alice/sales/')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Re-run check'})).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Open folder'})).not.toBeInTheDocument();

      mockCache.mockReturnValue(new Promise(() => {}));
      await user.click(screen.getByRole('link', {name: 'Open the team-data report'}));

      expect(await screen.findByText(/loading report/i)).toBeInTheDocument();
      expect(screen.queryByText('alice/sales/')).not.toBeInTheDocument();
    });

    it('keeps a loaded report, under a notice, through a re-read that does not get through', async () => {
      const {queryClient} = renderReport('/data-quality/alice/req-1');
      expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
      mockReport.mockResolvedValue({success: false, error: {message: '', code: 'NetworkUnavailable'}});

      await queryClient.invalidateQueries({queryKey: dataQualityKeys.report('alice', 'req-1')});

      const notice = (await screen.findByText('Couldn’t refresh this report')).closest('[role="alert"]');
      expect(notice).toHaveTextContent(/copy loaded earlier\. Can’t reach the server/);
      expect(screen.getByText('alice/sales/')).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Re-run check'})).toBeInTheDocument();
      expect(screen.queryByText('Report not available')).not.toBeInTheDocument();
    });

    it.each([
      ['finds it gone', notFound, /may still be running, or it may have been deleted/],
      [
        'fails with a code nobody listed',
        {success: false as const, error: {message: '', code: 'Unlisted'}},
        /went wrong/
      ]
    ])(
      'takes a loaded report off once a re-read %s, and a later re-read that does not get through leaves it off',
      async (_label, refusal, wording) => {
        // A failed refetch keeps the query's data: the report showed under "Report not available", whose
        // own words say it may have been deleted, and came back under the next read that did not get through.
        const {queryClient} = renderReport('/data-quality/alice/req-1');
        expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
        mockReport.mockResolvedValue(refusal);
        await queryClient.invalidateQueries({queryKey: dataQualityKeys.report('alice', 'req-1')});
        mockReport.mockResolvedValue({success: false, error: {message: '', code: 'RequestTimeout'}});

        await queryClient.invalidateQueries({queryKey: dataQualityKeys.report('alice', 'req-1')});

        expect(mockReport).toHaveBeenCalledTimes(3);
        const banner = (await screen.findByText('Report not available')).closest('[role="alert"]');
        expect(banner).toHaveTextContent(wording);
        expect(screen.queryByText('alice/sales/')).not.toBeInTheDocument();
        expect(screen.queryByText('Couldn’t refresh this report')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {name: 'Re-run check'})).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {name: 'Open folder'})).not.toBeInTheDocument();
      }
    );

    it('looks again for a report it could not find when a link on the open page comes back to it', async () => {
      // A refusal is never a fresh answer. Kept as one under the app's staleTime, a report looked for before it
      // was written stayed "not available" when the route, which does not remount, came back to it.
      const client = createTestQueryClient();
      client.setQueryDefaults(dataQualityKeys.all, {gcTime: Infinity, staleTime: 30_000});
      mockReport
        .mockResolvedValueOnce(notFound)
        .mockImplementation(async (_bucket, _space, id) =>
          ok(csvReport({location: id === 'req-2' ? 'alice/other/' : 'alice/sales/'}))
        );
      const {user} = renderReport(
        '/data-quality/alice/req-1',
        client,
        <>
          <Link to="/data-quality/alice/req-2">Open req-2</Link>
          <Link to="/data-quality/alice/req-1">Open req-1</Link>
        </>
      );
      expect(await screen.findByText('Report not available')).toBeInTheDocument();
      await user.click(screen.getByRole('link', {name: 'Open req-2'}));
      expect(await screen.findByText('alice/other/')).toBeInTheDocument();

      await user.click(screen.getByRole('link', {name: 'Open req-1'}));

      expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
      expect(mockReport).toHaveBeenCalledTimes(3);
      expect(mockReport).toHaveBeenLastCalledWith('user-space', 'alice', 'req-1');
      expect(screen.queryByText('Report not available')).not.toBeInTheDocument();
    });

    it('reads the spaces list again when a link followed on the open page names a space it lacks', async () => {
      // The route does not remount between two reports, so no read is owed: checked against the list the
      // page opened with, a space joined since was refused, and nothing ever read the list again.
      mockCache.mockResolvedValueOnce(NO_SPACES);
      const {user, queryClient} = renderReport(
        '/data-quality/alice/req-1',
        clientWithCachedList(60_000),
        <Link to="/data-quality/team-data/req-2">Open the team-data report</Link>
      );
      expect(await screen.findByText('alice/sales/')).toBeInTheDocument();
      await waitFor(() => expect(queryClient.isFetching({queryKey: connectionKeys.list('alice')})).toBe(0));
      expect(mockCache).toHaveBeenCalledOnce();

      let resolveRead: (result: typeof TEAM_DATA) => void = () => {};
      mockCache.mockReturnValue(new Promise((resolve) => (resolveRead = resolve)));
      await user.click(screen.getByRole('link', {name: 'Open the team-data report'}));

      expect(await screen.findByText(/loading report/i)).toBeInTheDocument();
      expect(screen.queryByText('Report not available')).not.toBeInTheDocument();
      expect(mockCache).toHaveBeenCalledTimes(2);

      resolveRead(TEAM_DATA);
      await waitFor(() => expect(mockReport).toHaveBeenLastCalledWith('shared-space', 'team-data', 'req-2'));
      expect(screen.queryByText('Report not available')).not.toBeInTheDocument();
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

    it.each([
      ['a personal space', '/data-quality/alice/req-1', 'alice'],
      ['a shared space', '/data-quality/team-data/req-1', 'team-data']
    ])('refuses Re-run on a report of the top of %s, saying why, and starts nothing', async (_space, path, root) => {
      // Only a report written before the server refused the top of a space can name it, and a
      // report written then stored the location normalised, without the trailing slash.
      mockReport.mockResolvedValue(ok(csvReport({location: root})));
      const {user} = renderReport(path);
      const rerun = await screen.findByRole('button', {name: 'Re-run check'});

      await user.click(rerun);

      expect(rerun).toHaveAttribute('aria-disabled', 'true');
      expect(rerun).toHaveAccessibleDescription(CHECK_AT_ROOT_REFUSAL);
      expect(mockEnqueue).not.toHaveBeenCalled();
    });

    it('still re-runs a single file that sits at the top of a space', async () => {
      // The server allows it — every query over one file carries a path predicate — so the
      // refusal must not reach a file just because its folder is the root.
      mockReport.mockResolvedValue(ok(csvReport({location: 'alice/top.csv'})));
      const {user} = renderReport('/data-quality/alice/req-1');

      await user.click(await screen.findByRole('button', {name: 'Re-run check'}));

      await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
      expect(mockEnqueue.mock.calls[0][0]).toMatchObject({location: 'alice/top.csv'});
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
});

// ─── from DataQualityReportPage.a11y.test.tsx ───

describe('DataQualityReportPage.a11y', () => {
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

    it('has no axe violations with the sampled rows and the per-file counts on screen', async () => {
      // The two widest additions: a scrollable table of user values, and a disclosure.
      mockReport.mockResolvedValue({
        success: true,
        data: csvReport({exact: {...csvReport().exact, duplicateSamples: duplicateSamples()}})
      });
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
});
