import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {QueryResultsTable} from './QueryResultsTable';
import {DEFAULT_COLUMN_WIDTH, MIN_COLUMN_WIDTH, COLUMN_RESIZE_STEP_PX} from './query.constants';

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
    queryExecutionId: 'exec-1' as string | null,
    onPrev: vi.fn(),
    onNext: vi.fn(),
    ...over
  };
  const utils = render(<QueryResultsTable {...props} />);
  return {...props, ...utils};
}

// A single data-column handle is found by its accessible name (FR-006).
function handleFor(name: string) {
  return screen.getByRole('separator', {name: `Resize column ${name}`});
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

  // SPEC-064 ---------------------------------------------------------------

  it('renders a resize handle per data column but not for the # row-number column', () => {
    renderTable();

    expect(handleFor('region')).toBeInTheDocument();
    expect(handleFor('revenue')).toBeInTheDocument();
    // Two data columns → two handles, none for `#`.
    expect(screen.getAllByRole('separator')).toHaveLength(2);
  });

  it('defaults each data column to DEFAULT_COLUMN_WIDTH (the # column stays fixed)', () => {
    const {container} = renderTable();
    const cols = container.querySelectorAll('col');
    expect(cols).toHaveLength(3); // # + 2 data columns
    expect((cols[1] as HTMLElement).style.width).toBe(`${DEFAULT_COLUMN_WIDTH}px`);
    expect((cols[2] as HTMLElement).style.width).toBe(`${DEFAULT_COLUMN_WIDTH}px`);
  });

  it('a drag widens the column, and the width persists across a page change', () => {
    const {container, rerender, ...props} = renderTable();

    const handle = handleFor('region');
    fireEvent.pointerDown(handle, {clientX: 0});
    fireEvent.pointerMove(window, {clientX: 100}); // +100px
    fireEvent.pointerUp(window);
    expect((container.querySelectorAll('col')[1] as HTMLElement).style.width).toBe(`${DEFAULT_COLUMN_WIDTH + 100}px`);

    // Page forward within the SAME execution → width survives (FR-002).
    rerender(
      <QueryResultsTable
        {...props}
        rows={[['ap-south', '55000']]}
        pageIndex={1}
        rangeStart={3}
        rangeEnd={3}
      />
    );
    expect((container.querySelectorAll('col')[1] as HTMLElement).style.width).toBe(`${DEFAULT_COLUMN_WIDTH + 100}px`);
  });

  it('clamps a drag at MIN_COLUMN_WIDTH', () => {
    const {container} = renderTable();
    const handle = handleFor('region');
    fireEvent.pointerDown(handle, {clientX: 500});
    fireEvent.pointerMove(window, {clientX: 0}); // far narrower than the floor
    expect((container.querySelectorAll('col')[1] as HTMLElement).style.width).toBe(`${MIN_COLUMN_WIDTH}px`);
  });

  it('double-clicking a handle resets that column to the default', () => {
    const {container} = renderTable();
    const handle = handleFor('revenue');
    fireEvent.pointerDown(handle, {clientX: 0});
    fireEvent.pointerMove(window, {clientX: 120});
    fireEvent.pointerUp(window);
    expect((container.querySelectorAll('col')[2] as HTMLElement).style.width).toBe(`${DEFAULT_COLUMN_WIDTH + 120}px`);

    fireEvent.doubleClick(handle);
    expect((container.querySelectorAll('col')[2] as HTMLElement).style.width).toBe(`${DEFAULT_COLUMN_WIDTH}px`);
  });

  it('keyboard Arrow Right widens the focused column by the resize step', () => {
    const {container} = renderTable();
    fireEvent.keyDown(handleFor('region'), {key: 'ArrowRight'});
    expect((container.querySelectorAll('col')[1] as HTMLElement).style.width).toBe(
      `${DEFAULT_COLUMN_WIDTH + COLUMN_RESIZE_STEP_PX}px`
    );
  });

  it('running a new query (new execution id) resets widths to the default', () => {
    const {container, rerender, ...props} = renderTable();
    fireEvent.keyDown(handleFor('region'), {key: 'ArrowRight'});
    expect((container.querySelectorAll('col')[1] as HTMLElement).style.width).toBe(
      `${DEFAULT_COLUMN_WIDTH + COLUMN_RESIZE_STEP_PX}px`
    );

    rerender(
      <QueryResultsTable
        {...props}
        queryExecutionId="exec-2"
      />
    );
    expect((container.querySelectorAll('col')[1] as HTMLElement).style.width).toBe(`${DEFAULT_COLUMN_WIDTH}px`);
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
