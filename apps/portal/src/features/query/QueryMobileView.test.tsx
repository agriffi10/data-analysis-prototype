import {describe, it, expect, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {QueryMobileView} from './QueryMobileView';
import {QUERY_HISTORY_PAGE_SIZE} from './query.constants';
import type {QueryHistoryEntry, SavedQuery} from './query.types';

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
