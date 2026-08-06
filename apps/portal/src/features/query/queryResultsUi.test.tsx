import {describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, within} from '@testing-library/react';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {QueryMobileView} from './QueryMobileView';
import {COLUMN_RESIZE_STEP_PX, DEFAULT_COLUMN_WIDTH, QUERY_HISTORY_PAGE_SIZE} from './query.constants';
import {QueryResultsMobile} from './QueryResultsMobile';
import {QueryResultsTable} from './QueryResultsTable';
import {QueryStatusBar} from './QueryStatusBar';
import type {QueryHistoryEntry, QueryStatus, SavedQuery} from './query.types';
import type {UseQueryResultsResult} from './useQueryResults';
import userEvent from '@testing-library/user-event';

// ─── from QueryMobileView.test.tsx ───
describe('QueryMobileView', () => {
  const savedQueries: SavedQuery[] = [
    {
      id: 's1',
      name: 'Revenue by region',
      sql: 'SELECT region,\n  sum(total)\nFROM alice.sales',
      database: 'alice',
      createdAt: '2026-07-01T10:00:00.000Z',
      updatedAt: '2026-07-02T10:00:00.000Z'
    },
    {
      id: 's2',
      name: 'Row counts',
      sql: 'SELECT count(*) FROM alice.sales',
      database: 'alice',
      createdAt: '2026-07-01T10:00:00.000Z',
      updatedAt: '2026-07-03T10:00:00.000Z'
    }
  ];

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
    const onTabChange = props.onTabChange ?? vi.fn();
    const user = userEvent.setup();
    const result = render(
      <QueryMobileView
        tab="saved"
        onTabChange={onTabChange}
        savedQueries={savedQueries}
        savedLoading={false}
        savedError={null}
        history={[historyEntry(1), historyEntry(2)]}
        historyLoading={false}
        historyError={null}
        onRun={onRun}
        onView={onView}
        runDisabled={false}
        {...props}
      />
    );
    return {...result, user, onRun, onView, onTabChange};
  }

  describe('QueryMobileView (SPEC-100 FR-004)', () => {
    it('lands on Saved and lists each saved query with a one-line SQL preview', () => {
      renderView();
      expect(screen.getByRole('button', {name: 'Saved'})).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('button', {name: 'History'})).toHaveAttribute('aria-pressed', 'false');
      // Most-recently-updated first, and the multi-line SQL collapses to one line.
      const names = screen.getAllByText(/Revenue by region|Row counts/).map((n) => n.textContent);
      expect(names).toEqual(['Row counts', 'Revenue by region']);
      expect(screen.getByText('SELECT region, sum(total) FROM alice.sales')).toBeInTheDocument();
    });

    it('runs a saved query and opens it read-only from the same card', async () => {
      const {user, onRun, onView} = renderView();
      await user.click(screen.getByRole('button', {name: 'Run saved query Revenue by region'}));
      expect(onRun).toHaveBeenCalledWith(savedQueries[0].sql, 'Revenue by region');
      await user.click(screen.getByRole('button', {name: 'View saved query Revenue by region'}));
      expect(onView).toHaveBeenCalledWith(savedQueries[0].sql, 'Revenue by region');
    });

    it('disables Run on every card while a run is in flight', () => {
      renderView({runDisabled: true});
      for (const button of screen.getAllByRole('button', {name: /^Run saved query/})) {
        expect(button).toBeDisabled();
      }
    });

    it('reports a switch to History to its owner', async () => {
      const {user, onTabChange} = renderView();
      await user.click(screen.getByRole('button', {name: 'History'}));
      expect(onTabChange).toHaveBeenCalledWith('history');
    });

    it('runs a history entry through the same handler', async () => {
      const {user, onRun} = renderView({tab: 'history'});
      expect(screen.getAllByRole('button', {name: 'Run this query'})).toHaveLength(2);
      // No editor to open into on mobile — the entry's other action is View.
      expect(screen.getAllByRole('button', {name: 'View this query'})).toHaveLength(2);
      await user.click(screen.getAllByRole('button', {name: 'Run this query'})[0]);
      expect(onRun).toHaveBeenCalledWith('SELECT 1', 'Query');
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
      expect(screen.getByText('No saved queries yet')).toBeInTheDocument();
      unmount();

      renderView({tab: 'history', history: [], historyError: new Error('boom')});
      expect(screen.getByText('Couldn’t load history.')).toBeInTheDocument();
      expect(screen.queryByText('No queries yet')).not.toBeInTheDocument();
    });

    it('has no axe violations', async () => {
      await expectNoA11yViolations(
        <QueryMobileView
          tab="saved"
          onTabChange={vi.fn()}
          savedQueries={savedQueries}
          savedLoading={false}
          savedError={null}
          history={[historyEntry(1)]}
          historyLoading={false}
          historyError={null}
          onRun={vi.fn()}
          onView={vi.fn()}
          runDisabled={false}
        />,
        COMPONENT_AXE_OPTIONS
      );
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

    it('goes back to the browse home and re-runs the same SQL', async () => {
      const {user, onBack, onRun} = renderResults();
      await user.click(screen.getByRole('button', {name: 'Back to queries'}));
      expect(onBack).toHaveBeenCalled();
      await user.click(screen.getByRole('button', {name: 'Run'}));
      expect(onRun).toHaveBeenCalled();
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

    it('has no axe violations', async () => {
      await expectNoA11yViolations(
        <QueryResultsMobile
          title="Revenue by region"
          sql={SQL}
          onBack={vi.fn()}
          onRun={vi.fn()}
          runDisabled={false}
          status={{queryExecutionId: 'q-1', state: 'SUCCEEDED'}}
          isInFlight={false}
          startedAt={null}
          hasResultSet
          totalRowCount={2}
          hasRun
          errorMessage={null}
          onDismissError={vi.fn()}
          results={resultsFixture()}
          displayExecutionId="q-1"
        />,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from QueryResultsTable.test.tsx ───
describe('QueryResultsTable', () => {
  const columns = [
    {name: 'region', type: 'string'},
    {name: 'revenue', type: 'double'}
  ];

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

    it('shows a loading state instead of the empty state while the first page is in flight', () => {
      renderTable({rows: [], columns: [], isLoading: true});

      expect(screen.getByText('Loading results…')).toBeInTheDocument();
      expect(screen.queryByText('No rows returned.')).not.toBeInTheDocument();
    });

    it('disables Prev on the first page and Next on the last page', () => {
      renderTable({hasPrev: false, hasNext: false});

      expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Next'})).toBeDisabled();
    });

    it('calls onNext / onPrev when the pager controls are clicked', () => {
      const props = renderTable({hasPrev: true, hasNext: true});

      fireEvent.click(screen.getByRole('button', {name: 'Next'}));
      fireEvent.click(screen.getByRole('button', {name: 'Prev'}));

      expect(props.onNext).toHaveBeenCalledTimes(1);
      expect(props.onPrev).toHaveBeenCalledTimes(1);
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

    it('drives the <colgroup> from the widths prop (the # column stays fixed)', () => {
      const {container} = renderTable({widths: [240, 96]});
      const cols = container.querySelectorAll('col');
      expect(cols).toHaveLength(3); // # + 2 data columns
      expect((cols[1] as HTMLElement).style.width).toBe('240px');
      expect((cols[2] as HTMLElement).style.width).toBe('96px');
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

    it('keyboard Arrow Right calls onResize widening the column by the resize step', () => {
      const {onResize} = renderTable({widths: [DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]});
      fireEvent.keyDown(handleFor('region'), {key: 'ArrowRight'});
      expect(onResize).toHaveBeenLastCalledWith(0, DEFAULT_COLUMN_WIDTH + COLUMN_RESIZE_STEP_PX);
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

    it('shows the exact total with thousands separators once counted (SPEC-080)', () => {
      render(
        <QueryStatusBar
          status={status({dataScannedBytes: 1_258_291, engineExecutionTimeMillis: 800})}
          isInFlight={false}
          startedAt={null}
          rowCount={20}
          hasMoreRows
          totalRowCount={1384}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByText(/1,384 rows/)).toBeInTheDocument();
      expect(screen.queryByText(/20\+ rows/)).not.toBeInTheDocument();
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

    it('shows no row-count stat for a DDL/no-result statement (SPEC-080 FR-004)', () => {
      render(
        <QueryStatusBar
          status={status({dataScannedBytes: 1024, engineExecutionTimeMillis: 40})}
          isInFlight={false}
          startedAt={null}
          hasResultSet={false}
          canSaveResults={false}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByText('Succeeded')).toBeInTheDocument();
      expect(screen.queryByText(/rows/)).not.toBeInTheDocument();
      expect(screen.getByText(/scanned/)).toBeInTheDocument();
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

    it('renders terminal Failed and Cancelled indicators', () => {
      const {rerender} = render(
        <QueryStatusBar
          status={status({state: 'FAILED'})}
          isInFlight={false}
          startedAt={null}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByText('Failed')).toBeInTheDocument();

      rerender(
        <QueryStatusBar
          status={status({state: 'CANCELLED'})}
          isInFlight={false}
          startedAt={null}
          onSaveResults={vi.fn()}
        />
      );
      expect(screen.getByText('Cancelled')).toBeInTheDocument();
    });
  });
});
