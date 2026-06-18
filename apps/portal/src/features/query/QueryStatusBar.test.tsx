import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryStatusBar } from './QueryStatusBar';
import type { QueryStatus } from './query.types';

function status(partial: Partial<QueryStatus>): QueryStatus {
  return { queryExecutionId: 'q-1', state: 'SUCCEEDED', ...partial };
}

describe('QueryStatusBar', () => {
  it('shows a running indicator while in flight', () => {
    render(
      <QueryStatusBar
        status={status({ state: 'RUNNING' })}
        isInFlight
        startedAt={Date.now() - 3000}
        onDownloadCsv={vi.fn()}
      />,
    );
    expect(screen.getByText('Running…')).toBeInTheDocument();
    expect(screen.getByText(/elapsed/)).toBeInTheDocument();
  });

  it('shows row/scanned/duration stats + Download CSV on success', () => {
    const onDownloadCsv = vi.fn();
    render(
      <QueryStatusBar
        status={status({
          state: 'SUCCEEDED',
          dataScannedBytes: 1_258_291,
          engineExecutionTimeMillis: 800,
        })}
        isInFlight={false}
        startedAt={null}
        rowCount={4}
        hasMoreRows={false}
        onDownloadCsv={onDownloadCsv}
      />,
    );

    expect(screen.getByText('Succeeded')).toBeInTheDocument();
    expect(screen.getByText(/4 rows · 1\.2 MB scanned · 800 ms/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Download CSV/ }));
    expect(onDownloadCsv).toHaveBeenCalledTimes(1);
  });

  it('renders terminal Failed and Cancelled indicators', () => {
    const { rerender } = render(
      <QueryStatusBar
        status={status({ state: 'FAILED' })}
        isInFlight={false}
        startedAt={null}
        onDownloadCsv={vi.fn()}
      />,
    );
    expect(screen.getByText('Failed')).toBeInTheDocument();

    rerender(
      <QueryStatusBar
        status={status({ state: 'CANCELLED' })}
        isInFlight={false}
        startedAt={null}
        onDownloadCsv={vi.fn()}
      />,
    );
    expect(screen.getByText('Cancelled')).toBeInTheDocument();
  });
});
