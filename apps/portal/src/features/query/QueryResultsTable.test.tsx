import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryResultsTable } from './QueryResultsTable';

const columns = [
  { name: 'region', type: 'string' },
  { name: 'revenue', type: 'double' },
];

describe('QueryResultsTable', () => {
  it('renders columns (name + type) and rows', () => {
    render(
      <QueryResultsTable
        columns={columns}
        rows={[
          ['us-east', '1284300'],
          ['eu-west', '902145'],
        ]}
        hasMore={false}
        isLoadingMore={false}
        onLoadMore={vi.fn()}
      />,
    );

    expect(screen.getByText('region')).toBeInTheDocument();
    expect(screen.getByText('double')).toBeInTheDocument();
    expect(screen.getByText('us-east')).toBeInTheDocument();
    expect(screen.getByText('2 rows')).toBeInTheDocument();
  });

  it('renders a friendly empty state for zero rows (e.g. DDL)', () => {
    render(
      <QueryResultsTable
        columns={[]}
        rows={[]}
        hasMore={false}
        isLoadingMore={false}
        onLoadMore={vi.fn()}
      />,
    );

    expect(screen.getByText('No rows returned.')).toBeInTheDocument();
  });

  it('shows Load more and calls onLoadMore when there are more pages', () => {
    const onLoadMore = vi.fn();
    render(
      <QueryResultsTable
        columns={columns}
        rows={[['us-east', '1']]}
        hasMore
        isLoadingMore={false}
        onLoadMore={onLoadMore}
      />,
    );

    // "1+ row" reflects there's at least one more page.
    expect(screen.getByText('1+ row')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });
});
