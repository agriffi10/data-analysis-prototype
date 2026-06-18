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
    fireEvent.click(screen.getByRole('button', { name: 'Open' }));
    expect(onReopen).toHaveBeenCalledWith(sample);
  });
});
