import * as service from './queryHistory.service';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {QueryHistoryPanel} from './QueryHistoryPanel';
import {queryKeys} from './queryKeys';
import type {QueryHistory, QueryHistoryEntry} from './query.types';

vi.mock('./queryHistory.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {
    ...actual,
    getQueryHistory: vi.fn(),
    appendQueryHistory: vi.fn(),
    updateQueryHistoryEntry: vi.fn()
  };
});

// ─── from QueryHistoryPanel.test.tsx ───
describe('QueryHistoryPanel', () => {
  // Integration style (react.md §21): render the REAL QueryHistoryPanel + its real
  // useQueryHistory hook + the real Drawer/Pager/QueryHistoryRow children, and mock
  // ONLY the AWS boundary — the query-history S3 service. The panel reads history
  // through getQueryHistory and re-reads it on Refresh; append/update aren't invoked
  // by the panel, so they stay inert spies.
  const mock = vi.mocked(service);

  const ok = (entries: QueryHistoryEntry[]) => ({success: true as const, data: {version: 1, entries} as QueryHistory});
  const fail = (message: string) => ({success: false as const, error: {message}});

  const sample: QueryHistoryEntry = {
    queryExecutionId: 'q1',
    sql: 'SELECT 1',
    database: 'alice',
    submittedAt: new Date().toISOString(),
    status: 'SUCCEEDED'
  };

  function makeEntries(n: number): QueryHistoryEntry[] {
    return Array.from({length: n}, (_, i) => ({
      queryExecutionId: `id${i}`,
      sql: `q${i}`,
      database: 'alice',
      submittedAt: new Date().toISOString(),
      status: 'SUCCEEDED' as const
    }));
  }

  const baseProps = {
    open: true,
    onClose: vi.fn(),
    username: 'alice',
    onReopen: vi.fn(),
    onRerun: vi.fn(),
    rerunDisabled: false
  };

  function renderPanel(props: Partial<typeof baseProps> = {}) {
    return renderWithProviders(
      <QueryHistoryPanel
        {...baseProps}
        {...props}
      />
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mock.getQueryHistory.mockResolvedValue(ok([]));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('QueryHistoryPanel', () => {
    it('renders no dialog while closed', () => {
      renderPanel({open: false});
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('lists history entries and reopens one on Open', async () => {
      mock.getQueryHistory.mockResolvedValue(ok([sample]));
      const onReopen = vi.fn();
      const {user} = renderPanel({onReopen});
      expect(screen.getByRole('dialog', {name: 'Query history'})).toBeInTheDocument();
      expect(await screen.findByText('SELECT 1')).toBeInTheDocument();
      await user.click(screen.getByRole('button', {name: /open this query/i}));
      expect(onReopen).toHaveBeenCalledWith(sample);
    });

    it('shows the empty state with no pager when there is no history', async () => {
      renderPanel();
      expect(await screen.findByText('No queries yet')).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Next'})).not.toBeInTheDocument();
    });

    it('surfaces a read error as a danger banner', async () => {
      mock.getQueryHistory.mockResolvedValue(fail('access denied'));
      renderPanel();
      expect(await screen.findByText(/Couldn’t load history/)).toBeInTheDocument();
    });

    // --- pagination (7 per page, newest-first) ---

    it('paginates 7-per-page with Prev/Next, disabling the controls at the ends', async () => {
      mock.getQueryHistory.mockResolvedValue(ok(makeEntries(23)));
      const {user} = renderPanel();

      // Page 1 = newest 7; Prev disabled, Next enabled.
      expect(await screen.findByText('q0')).toBeInTheDocument();
      expect(screen.getByText('q6')).toBeInTheDocument();
      expect(screen.queryByText('q7')).not.toBeInTheDocument();
      expect(screen.getByText(/^1.7 of 23$/)).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();
      const next = screen.getByRole('button', {name: 'Next'});
      expect(next).toBeEnabled();

      // Next replaces (not appends) the visible page.
      await user.click(next);
      expect(screen.getByText('q7')).toBeInTheDocument();
      expect(screen.getByText('q13')).toBeInTheDocument();
      expect(screen.queryByText('q0')).not.toBeInTheDocument();
      expect(screen.getByText(/^8.14 of 23$/)).toBeInTheDocument();

      // Advance to the last (partial) page → Next disabled, Prev enabled.
      await user.click(next);
      await user.click(next);
      expect(screen.getByText(/^22.23 of 23$/)).toBeInTheDocument();
      expect(screen.getByText('q22')).toBeInTheDocument();
      expect(next).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Prev'})).toBeEnabled();

      // Prev returns to the newest page.
      await user.click(screen.getByRole('button', {name: 'Prev'}));
      expect(screen.getByText(/^15.21 of 23$/)).toBeInTheDocument();
    });

    it('disables both controls with a single page of entries', async () => {
      mock.getQueryHistory.mockResolvedValue(ok(makeEntries(5)));
      renderPanel();
      expect(await screen.findByText(/^1.5 of 5$/)).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Next'})).toBeDisabled();
    });

    it('resets to page 1 when the list grows (a fresh run appended elsewhere)', async () => {
      mock.getQueryHistory.mockResolvedValue(ok(makeEntries(23)));
      const {user, queryClient} = renderPanel();
      await screen.findByText('q0');
      await user.click(screen.getByRole('button', {name: 'Next'}));
      expect(screen.getByText(/^8.14 of 23$/)).toBeInTheDocument();

      // The workspace appends a new entry → the shared cache grows → newest visible.
      mock.getQueryHistory.mockResolvedValue(ok(makeEntries(24)));
      await act(async () => {
        queryClient.setQueryData(queryKeys.history('alice'), {version: 1, entries: makeEntries(24)});
      });
      expect(await screen.findByText(/^1.7 of 24$/)).toBeInTheDocument();
    });

    it('clamps to the last valid page when the list shrinks', async () => {
      mock.getQueryHistory.mockResolvedValue(ok(makeEntries(23)));
      const {user, queryClient} = renderPanel();
      await screen.findByText('q0');
      const next = screen.getByRole('button', {name: 'Next'});
      await user.click(next);
      await user.click(next);
      await user.click(next); // last page (22–23 of 23)
      expect(screen.getByText(/^22.23 of 23$/)).toBeInTheDocument();

      mock.getQueryHistory.mockResolvedValue(ok(makeEntries(8)));
      await act(async () => {
        queryClient.setQueryData(queryKeys.history('alice'), {version: 1, entries: makeEntries(8)});
      });
      expect(await screen.findByText(/^8.8 of 8$/)).toBeInTheDocument();
      expect(screen.queryByText(/of 23/)).not.toBeInTheDocument();
    });

    it('resets to page 1 when reopened', async () => {
      mock.getQueryHistory.mockResolvedValue(ok(makeEntries(23)));
      const {user, rerender} = renderPanel();
      await screen.findByText('q0');
      await user.click(screen.getByRole('button', {name: 'Next'}));
      expect(screen.getByText(/^8.14 of 23$/)).toBeInTheDocument();

      rerender(
        <QueryHistoryPanel
          {...baseProps}
          open={false}
        />
      );
      rerender(
        <QueryHistoryPanel
          {...baseProps}
          open={true}
        />
      );
      expect(screen.getByText(/^1.7 of 23$/)).toBeInTheDocument();
    });

    // --- Refresh control ---

    it('re-reads the store on Refresh and returns to the newest page', async () => {
      mock.getQueryHistory.mockResolvedValue(ok(makeEntries(23)));
      const {user} = renderPanel();
      await screen.findByText('q0');
      await user.click(screen.getByRole('button', {name: 'Next'}));
      expect(screen.getByText(/^8.14 of 23$/)).toBeInTheDocument();
      expect(mock.getQueryHistory).toHaveBeenCalledTimes(1);

      await user.click(screen.getByRole('button', {name: 'Refresh history'}));
      expect(await screen.findByText(/^1.7 of 23$/)).toBeInTheDocument();
      expect(mock.getQueryHistory).toHaveBeenCalledTimes(2);
    });

    it('disables Refresh while a refresh is in flight, re-enabling once it settles', async () => {
      mock.getQueryHistory.mockResolvedValue(ok([sample]));
      const {user} = renderPanel();
      await screen.findByText('SELECT 1');

      // Make the refetch hang so the in-flight state is observable, then release it.
      let release: (() => void) | undefined;
      mock.getQueryHistory.mockImplementationOnce(
        () => new Promise((resolve) => (release = () => resolve(ok([sample]))))
      );
      await user.click(screen.getByRole('button', {name: 'Refresh history'}));
      await waitFor(() => expect(screen.getByRole('button', {name: 'Refresh history'})).toBeDisabled());

      act(() => release?.());
      await waitFor(() => expect(screen.getByRole('button', {name: 'Refresh history'})).toBeEnabled());
    });

    it('shows the banner on a refresh error without dropping the loaded list', async () => {
      mock.getQueryHistory.mockResolvedValue(ok([sample]));
      const {user} = renderPanel();
      await screen.findByText('SELECT 1');

      mock.getQueryHistory.mockResolvedValue(fail('access denied'));
      await user.click(screen.getByRole('button', {name: 'Refresh history'}));
      // TanStack keeps the last-good data on a failed refetch: banner + list both show.
      expect(await screen.findByText(/Couldn’t load history/)).toBeInTheDocument();
      expect(screen.getByText('SELECT 1')).toBeInTheDocument();
    });
  });
});
