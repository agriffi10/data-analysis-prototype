import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryHistoryRow } from './QueryHistoryRow';
import type { QueryHistoryEntry } from './query.types';

function entry(overrides: Partial<QueryHistoryEntry> = {}): QueryHistoryEntry {
  return {
    queryExecutionId: 'q1',
    sql: 'SELECT region,\n  SUM(amount)\nFROM sales',
    database: 'alice',
    submittedAt: new Date().toISOString(),
    status: 'SUCCEEDED',
    dataScannedBytes: 2048,
    durationMs: 800,
    ...overrides,
  };
}

describe('QueryHistoryRow', () => {
  it('renders the status, single-line SQL preview, and stats', () => {
    render(<QueryHistoryRow entry={entry()} onReopen={vi.fn()} onRerun={vi.fn()} rerunDisabled={false} />);
    expect(screen.getByText('Succeeded')).toBeInTheDocument();
    // Whitespace collapsed to a single line.
    expect(screen.getByText('SELECT region, SUM(amount) FROM sales')).toBeInTheDocument();
    expect(screen.getByText('2.0 KB scanned · 800 ms')).toBeInTheDocument();
  });

  it('fires onReopen / onRerun from the actions', () => {
    const onReopen = vi.fn();
    const onRerun = vi.fn();
    render(<QueryHistoryRow entry={entry()} onReopen={onReopen} onRerun={onRerun} rerunDisabled={false} />);
    fireEvent.click(screen.getByRole('button', { name: /open this query/i }));
    fireEvent.click(screen.getByRole('button', { name: /re-run this query/i }));
    expect(onReopen).toHaveBeenCalledTimes(1);
    expect(onRerun).toHaveBeenCalledTimes(1);
  });

  it('disables Re-run while a query is in flight', () => {
    render(<QueryHistoryRow entry={entry()} onReopen={vi.fn()} onRerun={vi.fn()} rerunDisabled />);
    expect(screen.getByRole('button', { name: /re-run this query/i })).toBeDisabled();
  });

  it('shows a neutral "Unknown" badge for a stale non-terminal entry', () => {
    render(
      <QueryHistoryRow
        entry={entry({ status: 'RUNNING', dataScannedBytes: undefined, durationMs: undefined })}
        onReopen={vi.fn()}
        onRerun={vi.fn()}
        rerunDisabled={false}
      />
    );
    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });
});
