import {describe, it, expect, vi} from 'vitest';
import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {QueryResultsMobile} from './QueryResultsMobile';
import type {UseQueryResultsResult} from './useQueryResults';

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
