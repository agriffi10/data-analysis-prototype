import {describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, within} from '@testing-library/react';
import {QueryMobileView} from './QueryMobileView';
import {QUERY_HISTORY_PAGE_SIZE} from './query.constants';
import {DEFAULT_COLUMN_WIDTH} from '../catalog/catalog.constants';
import {QueryResultsMobile} from './QueryResultsMobile';
import {QueryResultsTable} from './QueryResultsTable';
import {QueryStatusBar} from './QueryStatusBar';
import type {QueryHistoryEntry} from './query.types';
import type {SavedQuery} from '../saved-queries/savedQueries.types';
import type {QuerySpace, QueryStatus} from '../catalog/catalog.types';
import type {UseQueryResultsResult} from '../catalog/useQueryResults';
import userEvent from '@testing-library/user-event';

// ─── from QueryMobileView.test.tsx ───
describe('QueryMobileView', () => {
  const savedQueries: SavedQuery[] = [
    {
      spaceId: 'personal',
      bucket: 'user-space',
      key: 'alice/saved_queries/Revenue by region.sql',
      name: 'Revenue by region',
      updatedAt: '2026-07-02T10:00:00.000Z',
      size: 48
    },
    {
      spaceId: 'personal',
      bucket: 'user-space',
      key: 'alice/saved_queries/Row counts.sql',
      name: 'Row counts',
      updatedAt: '2026-07-03T10:00:00.000Z',
      size: 32
    }
  ];

  const PERSONAL_SPACE: QuerySpace = {
    id: 'personal',
    label: 'My files',
    bucket: 'user-space',
    rootPrefix: 'alice/',
    rootLabel: 'My Files'
  };

  const historyEntry = (i: number): QueryHistoryEntry => ({
    queryExecutionId: `q-${i}`,
    sql: `SELECT ${i}`,
    database: 'alice',
    submittedAt: `2026-07-0${(i % 9) + 1}T10:00:00.000Z`,
    status: 'SUCCEEDED'
  });

  function renderView(props: Partial<React.ComponentProps<typeof QueryMobileView>> = {}) {
    const onRun = props.onRun ?? vi.fn();
    const onView = props.onView ?? vi.fn();
    const onRunSaved = props.onRunSaved ?? vi.fn();
    const onViewSaved = props.onViewSaved ?? vi.fn();
    const onTabChange = props.onTabChange ?? vi.fn();
    const user = userEvent.setup();
    const result = render(
      <QueryMobileView
        tab="saved"
        onTabChange={onTabChange}
        spaces={[PERSONAL_SPACE]}
        space={PERSONAL_SPACE}
        onSelectSpace={vi.fn()}
        savedQueries={savedQueries}
        savedLoading={false}
        savedError={null}
        savedHasMore={false}
        onLoadMoreSaved={vi.fn()}
        savedLoadingMore={false}
        onDeleteSaved={vi.fn()}
        history={[historyEntry(1), historyEntry(2)]}
        historyLoading={false}
        historyError={null}
        onRun={onRun}
        onView={onView}
        onRunSaved={onRunSaved}
        onViewSaved={onViewSaved}
        runDisabled={false}
        {...props}
      />
    );
    return {...result, user, onRun, onView, onRunSaved, onViewSaved, onTabChange};
  }

  describe('QueryMobileView (SPEC-100 FR-004)', () => {
    it('lands on Saved and lists each saved query in S3’s own order, with no SQL preview', () => {
      renderView();
      expect(screen.getByRole('button', {name: 'Saved'})).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('button', {name: 'History'})).toHaveAttribute('aria-pressed', 'false');
      const names = screen.getAllByText(/Revenue by region|Row counts/).map((n) => n.textContent);
      expect(names).toEqual(['Revenue by region', 'Row counts']);
      // SPEC-173 FR-006: a `.sql` file has no body until it is read, so a row shows its
      // size and its time and nothing that would cost a GetObject.
      expect(screen.queryByText(/SELECT/)).not.toBeInTheDocument();
      expect(screen.getByText('48 B')).toBeInTheDocument();
    });

    it('hands the RECORD to its host, which fetches the file — no GetObject until a card is chosen', async () => {
      const {user, onRunSaved, onViewSaved} = renderView();
      await user.click(screen.getByRole('button', {name: 'Run saved query Revenue by region'}));
      expect(onRunSaved).toHaveBeenCalledWith(savedQueries[0]);
      await user.click(screen.getByRole('button', {name: 'View saved query Revenue by region'}));
      expect(onViewSaved).toHaveBeenCalledWith(savedQueries[0]);
    });

    it('reports a switch to History to its owner', async () => {
      const {user, onTabChange} = renderView();
      await user.click(screen.getByRole('button', {name: 'History'}));
      expect(onTabChange).toHaveBeenCalledWith('history');
    });

    it('pages History with Prev/Next rather than growing the list', async () => {
      const history = Array.from({length: QUERY_HISTORY_PAGE_SIZE + 2}, (_, i) => historyEntry(i + 1));
      const {user} = renderView({tab: 'history', history});
      expect(screen.getAllByRole('button', {name: 'Run this query'})).toHaveLength(QUERY_HISTORY_PAGE_SIZE);
      expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();

      await user.click(screen.getByRole('button', {name: 'Next'}));
      // Replace-style: the second page holds only the remaining entries.
      expect(screen.getAllByRole('button', {name: 'Run this query'})).toHaveLength(2);
      expect(screen.getByRole('button', {name: 'Next'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Prev'})).toBeEnabled();
    });

    it('shows an empty state per surface, and a failed read as a banner', () => {
      const {unmount} = renderView({savedQueries: []});
      expect(screen.getByText('No saved queries in My files')).toBeInTheDocument();
      unmount();

      renderView({tab: 'history', history: [], historyError: new Error('boom')});
      expect(screen.getByText('Couldn’t load history.')).toBeInTheDocument();
      expect(screen.queryByText('No queries yet')).not.toBeInTheDocument();
    });
  });
});

// ─── from QueryResultsMobile.test.tsx ───
describe('QueryResultsMobile', () => {
  const SQL = 'SELECT region, total FROM alice.sales';

  const resultsFixture = (over: Partial<UseQueryResultsResult> = {}): UseQueryResultsResult => ({
    columns: [
      {name: 'region', type: 'varchar'},
      {name: 'total', type: 'bigint'}
    ],
    rows: [
      ['us-east', '120'],
      ['eu-west', '85']
    ],
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
    ...over
  });

  function renderResults(props: Partial<React.ComponentProps<typeof QueryResultsMobile>> = {}) {
    const onBack = props.onBack ?? vi.fn();
    const onRun = props.onRun ?? vi.fn();
    const user = userEvent.setup();
    const result = render(
      <QueryResultsMobile
        title="Revenue by region"
        sql={SQL}
        onBack={onBack}
        onRun={onRun}
        runDisabled={false}
        status={{queryExecutionId: 'q-1', state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 800}}
        isInFlight={false}
        startedAt={null}
        hasResultSet
        totalRowCount={2}
        hasRun
        errorMessage={null}
        onDismissError={vi.fn()}
        results={props.results ?? resultsFixture()}
        displayExecutionId="q-1"
        {...props}
      />
    );
    return {...result, user, onBack, onRun};
  }

  describe('QueryResultsMobile (SPEC-100 FR-006)', () => {
    // The desktop pager's twin. Both prefer the exact background total over the paging-derived
    // one, which is null until the last page is loaded — and the rule being written twice is
    // exactly why this needs its own test: the desktop copy was fenced and this one was not,
    // so deleting it here restored "no total until you page to the end" on a phone alone.
    it('shows the exact total while the paging-derived one is still unknown', () => {
      renderResults({
        totalRowCount: 2384,
        results: resultsFixture({totalRowCount: null, hasNext: true, hasMoreServer: true})
      });

      expect(screen.getByText(/Rows 1–2 of 2384/)).toBeInTheDocument();
    });

    it('shows the SQL read-only — no editor to type into', () => {
      renderResults();
      expect(screen.getByText(SQL)).toBeInTheDocument();
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
      expect(screen.queryByLabelText('SQL editor')).not.toBeInTheDocument();
    });

    it('renders one card per row, mapping column name to value', () => {
      renderResults();
      // Each row is one labelled card of column → value pairs.
      const first = screen.getByLabelText('Row 1');
      expect(within(first).getByText('region')).toBeInTheDocument();
      expect(within(first).getByText('us-east')).toBeInTheDocument();
      expect(within(first).getByText('total')).toBeInTheDocument();
      expect(within(first).getByText('120')).toBeInTheDocument();
      expect(within(screen.getByLabelText('Row 2')).getByText('eu-west')).toBeInTheDocument();
    });

    it('reports the outcome in a status region, never by colour alone', () => {
      renderResults();
      const status = screen.getByRole('status');
      expect(within(status).getByText('Succeeded')).toBeInTheDocument();
      expect(within(status).getByText(/2 rows/)).toBeInTheDocument();
    });

    it('disables both pager controls when a single page holds every row', () => {
      renderResults();
      expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Next'})).toBeDisabled();
      expect(screen.getByText(/Rows 1–2 of 2/)).toBeInTheDocument();
    });

    it('pages with Prev/Next when more pages exist', async () => {
      const results = resultsFixture({hasPrev: true, hasNext: true, totalRowCount: null, pageIndex: 1});
      const {user} = renderResults({results});
      await user.click(screen.getByRole('button', {name: 'Next'}));
      expect(results.goNext).toHaveBeenCalled();
      await user.click(screen.getByRole('button', {name: 'Prev'}));
      expect(results.goPrev).toHaveBeenCalled();
      // Replace-style paging: no "Load more" affordance anywhere.
      expect(screen.queryByRole('button', {name: /load more/i})).not.toBeInTheDocument();
    });

    it('prompts to run when opened without a run, and shows the failure banner when one failed', () => {
      const {unmount} = renderResults({hasRun: false, displayExecutionId: null});
      expect(screen.getByText('Run this query to see results.')).toBeInTheDocument();
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Prev'})).not.toBeInTheDocument();
      unmount();

      renderResults({
        status: {queryExecutionId: 'q-1', state: 'FAILED'},
        displayExecutionId: null,
        errorMessage: 'Check the table name and try again.'
      });
      expect(screen.getByText('Query failed.')).toBeInTheDocument();
      expect(screen.getByText('Check the table name and try again.')).toBeInTheDocument();
    });
  });
});

// ─── from QueryResultsTable.test.tsx ───
describe('QueryResultsTable', () => {
  const columns = [
    {name: 'region', type: 'string'},
    {name: 'revenue', type: 'double'}
  ];

  // Both halves are load-bearing and neither works alone. The POSITIVE half proves the
  // reset reached the name; the CONTROL is asserted on that same `th` — not on some other
  // caption elsewhere — so that deleting SECTION_CAPTION from this header reddens the test
  // instead of satisfying it. jsdom loads no Tailwind, so `text-transform` itself is not
  // observable and the classes are all there is to assert on.
  it('shows a column name as spelled, inside a header that still uses the caption style', () => {
    renderTable();

    const name = screen.getByTitle('region');
    expect(name).toHaveClass('normal-case');
    expect(name.closest('th')).toHaveClass('uppercase');
  });

  // Sensible defaults for a single-page result; each test overrides what it needs.
  // Widths are controlled (owned by the parent's useColumnWidths) — default to the
  // two data columns at DEFAULT_COLUMN_WIDTH.
  function renderTable(over: Partial<Parameters<typeof QueryResultsTable>[0]> = {}) {
    const props = {
      columns,
      rows: [
        ['us-east', '1284300'],
        ['eu-west', '902145']
      ],
      pageIndex: 0,
      rangeStart: 1,
      rangeEnd: 2,
      totalRowCount: 2 as number | null,
      hasPrev: false,
      hasNext: false,
      isFetchingNext: false,
      isLoading: false,
      widths: [DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH],
      onResize: vi.fn(),
      onResetColumn: vi.fn(),
      onPrev: vi.fn(),
      onNext: vi.fn(),
      ...over
    };
    const utils = render(<QueryResultsTable {...props} />);
    return {...props, ...utils};
  }

  // A single data-column handle is found by its accessible name.
  function handleFor(name: string) {
    return screen.getByRole('separator', {name: `Resize column ${name}`});
  }

  describe('QueryResultsTable', () => {
    it('renders columns (name + type) and the current page rows', () => {
      renderTable();

      expect(screen.getByText('region')).toBeInTheDocument();
      expect(screen.getByText('double')).toBeInTheDocument();
      expect(screen.getByText('us-east')).toBeInTheDocument();
      expect(screen.getByText(/Rows 1–2 of 2/)).toBeInTheDocument();
    });

    it('numbers rows by absolute position (rangeStart offset), not the in-page index', () => {
      renderTable({
        rows: [['x'], ['y']],
        columns: [{name: 'c', type: 'string'}],
        pageIndex: 2,
        rangeStart: 41,
        rangeEnd: 42,
        totalRowCount: null,
        hasPrev: true,
        hasNext: true
      });

      expect(screen.getByText('41')).toBeInTheDocument();
      expect(screen.getByText('42')).toBeInTheDocument();
      // No definitive total until the last page is loaded.
      expect(screen.getByText(/Rows 41–42$/)).toBeInTheDocument();
    });

    it('renders a friendly empty state for zero rows (e.g. DDL) with no pager', () => {
      renderTable({rows: [], columns: [], totalRowCount: 0});

      expect(screen.getByText('No rows returned.')).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Next'})).not.toBeInTheDocument();
    });

    it('disables Prev on the first page and Next on the last page', () => {
      renderTable({hasPrev: false, hasNext: false});

      expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Next'})).toBeDisabled();
    });

    it('shows a loading label on Next and disables it while a forward page is fetching', () => {
      renderTable({hasNext: true, isFetchingNext: true});

      const next = screen.getByRole('button', {name: 'Loading…'});
      expect(next).toBeDisabled();
    });

    it('renders a resize handle per data column but not for the # row-number column', () => {
      renderTable();

      expect(handleFor('region')).toBeInTheDocument();
      expect(handleFor('revenue')).toBeInTheDocument();
      // Two data columns → two handles, none for `#`.
      expect(screen.getAllByRole('separator')).toHaveLength(2);
    });

    it('a drag calls onResize for that column with the new pixel width', () => {
      const {onResize} = renderTable({widths: [DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]});

      const handle = handleFor('region');
      fireEvent.pointerDown(handle, {clientX: 0});
      fireEvent.pointerMove(window, {clientX: 100}); // +100px from the gesture origin
      fireEvent.pointerUp(window);

      expect(onResize).toHaveBeenLastCalledWith(0, DEFAULT_COLUMN_WIDTH + 100);
    });

    it('double-clicking a handle calls onResetColumn for that column', () => {
      const {onResetColumn} = renderTable();
      fireEvent.doubleClick(handleFor('revenue'));
      expect(onResetColumn).toHaveBeenCalledWith(1);
    });

    it('truncates cells and headers and exposes the full text via a title tooltip', () => {
      renderTable({
        columns: [{name: 'a_very_long_column_name', type: 'varchar'}],
        rows: [['a value that is far wider than the column can show']]
      });

      const header = screen.getByText('a_very_long_column_name');
      expect(header).toHaveClass('truncate');
      expect(header).toHaveAttribute('title', 'a_very_long_column_name');

      const cell = screen.getByText('a value that is far wider than the column can show');
      expect(cell).toHaveClass('truncate');
      expect(cell).toHaveAttribute('title', 'a value that is far wider than the column can show');
    });
  });
});

// ─── from QueryStatusBar.test.tsx ───
describe('QueryStatusBar', () => {
  function status(partial: Partial<QueryStatus>): QueryStatus {
    return {queryExecutionId: 'q-1', state: 'SUCCEEDED', ...partial};
  }

  describe('QueryStatusBar', () => {
    it('shows a running indicator while in flight', () => {
      render(
        <QueryStatusBar
          status={status({state: 'RUNNING'})}
          isInFlight
          startedAt={Date.now() - 3000}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByText('Running…')).toBeInTheDocument();
      expect(screen.getByText(/elapsed/)).toBeInTheDocument();
    });

    it('shows row/scanned/duration stats + Save results on a row-returning success', () => {
      const onSaveResults = vi.fn();
      render(
        <QueryStatusBar
          status={status({
            state: 'SUCCEEDED',
            dataScannedBytes: 1_258_291,
            engineExecutionTimeMillis: 800
          })}
          isInFlight={false}
          startedAt={null}
          rowCount={4}
          hasMoreRows={false}
          canSaveResults
          onSaveResults={onSaveResults}
        />
      );

      expect(screen.getByText('Succeeded')).toBeInTheDocument();
      expect(screen.getByText(/4 rows · 1\.2 MB scanned · 800 ms/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', {name: /Save results to my files/}));
      expect(onSaveResults).toHaveBeenCalledTimes(1);
    });

    it('hides Save results when there is no savable result (DDL / no rows)', () => {
      render(
        <QueryStatusBar
          status={status({state: 'SUCCEEDED'})}
          isInFlight={false}
          startedAt={null}
          canSaveResults={false}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByText('Succeeded')).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: /Save results/})).not.toBeInTheDocument();
    });

    it('shows the loaded count with "+" while the exact total is still being counted (SPEC-080)', () => {
      render(
        <QueryStatusBar
          status={status({dataScannedBytes: 1_258_291, engineExecutionTimeMillis: 800})}
          isInFlight={false}
          startedAt={null}
          rowCount={20}
          hasMoreRows
          totalRowCount={null}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByText(/20\+ rows/)).toBeInTheDocument();
    });

    it('shows the exact total (no "+") for a large result set (SPEC-080)', () => {
      render(
        <QueryStatusBar
          status={status({})}
          isInFlight={false}
          startedAt={null}
          rowCount={20}
          hasMoreRows
          totalRowCount={2_450_991}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByText(/2,450,991 rows/)).toBeInTheDocument();
      expect(screen.queryByText(/\+ rows/)).not.toBeInTheDocument();
    });

    it('shows batch progress while a multi-statement script runs (SPEC-078 FR-004)', () => {
      render(
        <QueryStatusBar
          status={status({state: 'RUNNING'})}
          isInFlight
          startedAt={Date.now() - 3000}
          batch={{current: 2, total: 4}}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByRole('status')).toHaveTextContent('Statement 2 of 4');
    });

    it('summarizes a fully-run script on success, but not a halted one (SPEC-078)', () => {
      const {rerender} = render(
        <QueryStatusBar
          status={status({state: 'SUCCEEDED'})}
          isInFlight={false}
          startedAt={null}
          batch={{current: 3, total: 3}}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByRole('status')).toHaveTextContent('Script finished · 3 statements');

      rerender(
        <QueryStatusBar
          status={status({state: 'SUCCEEDED'})}
          isInFlight={false}
          startedAt={null}
          batch={{current: 1, total: 3}}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByRole('status')).not.toHaveTextContent('Script finished');
    });
  });
});
