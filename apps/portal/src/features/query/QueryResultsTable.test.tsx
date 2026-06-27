import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {QueryResultsTable} from './QueryResultsTable';

const columns = [
  {name: 'region', type: 'string'},
  {name: 'revenue', type: 'double'}
];

// Sensible defaults for a single-page result; each test overrides what it needs.
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
    onPrev: vi.fn(),
    onNext: vi.fn(),
    ...over
  };
  render(<QueryResultsTable {...props} />);
  return props;
}

describe('QueryResultsTable', () => {
  it('renders columns (name + type) and the current page rows', () => {
    renderTable();

    expect(screen.getByText('region')).toBeInTheDocument();
    expect(screen.getByText('double')).toBeInTheDocument();
    expect(screen.getByText('us-east')).toBeInTheDocument();
    // Range indicator + known total.
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
});
