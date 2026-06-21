import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('./useQueryHistory', () => ({ useQueryHistory: vi.fn() }));

import { useQueryHistory } from './useQueryHistory';
import { QueryHistoryPanel } from './QueryHistoryPanel';
import type { QueryHistoryEntry } from './query.types';

const mockUseHistory = vi.mocked(useQueryHistory);

function historyState(history: QueryHistoryEntry[], extra = {}) {
  return {
    history,
    isLoading: false,
    error: null,
    appendEntry: vi.fn(),
    updateEntry: vi.fn(),
    ...extra,
  } as ReturnType<typeof useQueryHistory>;
}

const sample: QueryHistoryEntry = {
  queryExecutionId: 'q1',
  sql: 'SELECT 1',
  database: 'alice',
  submittedAt: new Date().toISOString(),
  status: 'SUCCEEDED',
};

const baseProps = {
  open: true,
  onClose: vi.fn(),
  username: 'alice',
  onReopen: vi.fn(),
  onRerun: vi.fn(),
  rerunDisabled: false,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('QueryHistoryPanel', () => {
  it('renders nothing when closed', () => {
    mockUseHistory.mockReturnValue(historyState([]));
    render(<QueryHistoryPanel {...baseProps} open={false} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('lists history entries newest-first', () => {
    mockUseHistory.mockReturnValue(historyState([sample]));
    render(<QueryHistoryPanel {...baseProps} />);
    expect(screen.getByRole('dialog', { name: 'Query history' })).toBeInTheDocument();
    expect(screen.getByText('SELECT 1')).toBeInTheDocument();
  });

  it('shows a friendly empty state when there is no history', () => {
    mockUseHistory.mockReturnValue(historyState([]));
    render(<QueryHistoryPanel {...baseProps} />);
    expect(screen.getByText('No queries yet')).toBeInTheDocument();
  });

  it('shows a danger banner on a read error', () => {
    mockUseHistory.mockReturnValue(
      historyState([], { error: 'access denied' }),
    );
    render(<QueryHistoryPanel {...baseProps} />);
    expect(screen.getByText(/Couldn’t load history/)).toBeInTheDocument();
  });

  it('fires onReopen with the entry', () => {
    const onReopen = vi.fn();
    mockUseHistory.mockReturnValue(historyState([sample]));
    render(<QueryHistoryPanel {...baseProps} onReopen={onReopen} />);
    fireEvent.click(screen.getByRole('button', { name: /open this query/i }));
    expect(onReopen).toHaveBeenCalledWith(sample);
  });

  // --- SPEC-042 pagination (7 per page, newest-first) ---

  function makeEntries(n: number): QueryHistoryEntry[] {
    return Array.from({ length: n }, (_, i) => ({
      queryExecutionId: `id${i}`,
      sql: `q${i}`,
      database: 'alice',
      submittedAt: new Date().toISOString(),
      status: 'SUCCEEDED' as const,
    }));
  }

  it('shows the newest 7 on page 1 with Prev disabled', () => {
    mockUseHistory.mockReturnValue(historyState(makeEntries(23)));
    render(<QueryHistoryPanel {...baseProps} />);

    expect(screen.getByText('q0')).toBeInTheDocument();
    expect(screen.getByText('q6')).toBeInTheDocument();
    expect(screen.queryByText('q7')).not.toBeInTheDocument();
    expect(screen.getByText(/^1.7 of 23$/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
  });

  it('Next replaces the list with the next 7; Prev returns', () => {
    mockUseHistory.mockReturnValue(historyState(makeEntries(23)));
    render(<QueryHistoryPanel {...baseProps} />);

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText('q7')).toBeInTheDocument();
    expect(screen.getByText('q13')).toBeInTheDocument();
    expect(screen.queryByText('q0')).not.toBeInTheDocument(); // replaced, not appended
    expect(screen.getByText(/^8.14 of 23$/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Prev' }));
    expect(screen.getByText('q0')).toBeInTheDocument();
    expect(screen.getByText(/^1.7 of 23$/)).toBeInTheDocument();
  });

  it('disables Next on the last (partial) page', () => {
    mockUseHistory.mockReturnValue(historyState(makeEntries(23)));
    render(<QueryHistoryPanel {...baseProps} />);

    const next = screen.getByRole('button', { name: 'Next' });
    fireEvent.click(next); // 8–14
    fireEvent.click(next); // 15–21
    fireEvent.click(next); // 22–23 (last)
    expect(screen.getByText(/^22.23 of 23$/)).toBeInTheDocument();
    expect(screen.getByText('q22')).toBeInTheDocument();
    expect(next).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Prev' })).toBeEnabled();
  });

  it('disables both controls with 7 or fewer entries', () => {
    mockUseHistory.mockReturnValue(historyState(makeEntries(5)));
    render(<QueryHistoryPanel {...baseProps} />);
    expect(screen.getByText(/^1.5 of 5$/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('shows no pager in the empty state', () => {
    mockUseHistory.mockReturnValue(historyState([]));
    render(<QueryHistoryPanel {...baseProps} />);
    expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument();
  });

  it('resets to page 1 when reopened', () => {
    mockUseHistory.mockReturnValue(historyState(makeEntries(23)));
    const { rerender } = render(<QueryHistoryPanel {...baseProps} />);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText(/^8.14 of 23$/)).toBeInTheDocument();

    // Close then reopen → back to page 1.
    rerender(<QueryHistoryPanel {...baseProps} open={false} />);
    rerender(<QueryHistoryPanel {...baseProps} open={true} />);
    expect(screen.getByText(/^1.7 of 23$/)).toBeInTheDocument();
  });

  it('resets to page 1 when a new entry is appended', () => {
    mockUseHistory.mockReturnValue(historyState(makeEntries(23)));
    const { rerender } = render(<QueryHistoryPanel {...baseProps} />);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText(/^8.14 of 23$/)).toBeInTheDocument();

    // A fresh Run appends → list grows → newest visible on page 1.
    mockUseHistory.mockReturnValue(historyState(makeEntries(24)));
    rerender(<QueryHistoryPanel {...baseProps} />);
    expect(screen.getByText(/^1.7 of 24$/)).toBeInTheDocument();
  });

  it('clamps to the last valid page when the list shrinks', () => {
    mockUseHistory.mockReturnValue(historyState(makeEntries(23)));
    const { rerender } = render(<QueryHistoryPanel {...baseProps} />);
    const next = screen.getByRole('button', { name: 'Next' });
    fireEvent.click(next);
    fireEvent.click(next);
    fireEvent.click(next); // last page (22–23 of 23)
    expect(screen.getByText(/^22.23 of 23$/)).toBeInTheDocument();

    // List shrinks to 8 → only 2 pages; clamp to the last (8th entry → page 2).
    mockUseHistory.mockReturnValue(historyState(makeEntries(8)));
    rerender(<QueryHistoryPanel {...baseProps} />);
    expect(screen.getByText(/^8.8 of 8$/)).toBeInTheDocument();
    expect(screen.queryByText(/of 23/)).not.toBeInTheDocument();
  });
});
