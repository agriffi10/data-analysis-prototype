import {beforeEach, describe, expect, it, vi} from 'vitest';
import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {MAX_RESULTS_PAGE_SIZE, MIN_RESULTS_PAGE_SIZE} from './query.constants';
import {CreateViewDialog} from '../catalog/CreateViewDialog';
import {axe} from 'vitest-axe';
import {QueryHistoryRow} from './QueryHistoryRow';
import {ResultTabs} from './ResultTabs';
import {ResultsPageSizeControl} from './ResultsPageSizeControl';
import {SavedQueriesPanel} from './SavedQueriesPanel';
import {TableActionsMenu} from './TableActionsMenu';
import type {TableMenuItem} from './TableActionsMenu';
import {QueryTabStrip} from './QueryTabStrip';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import type {QueryHistoryEntry, QueryTab, ResultTab} from './query.types';
import type {SavedQuery, SavedQueryLink} from '../saved-queries/savedQueries.types';
import type {QuerySpace, QueryStatus} from '../catalog/catalog.types';

// A tab's link to the file it was opened from (SPEC-173) — the key IS the identity.
const LINK: SavedQueryLink = {
  spaceId: 'personal',
  bucket: 'user-space',
  key: 'alice/saved_queries/Monthly revenue.sql',
  name: 'Monthly revenue'
};

// ─── from CreateViewDialog.test.tsx ───
describe('CreateViewDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('CreateViewDialog (SPEC-048 FR-001/002)', () => {
    it('shows the derived target database read-only (SPEC-077 FR-008)', () => {
      render(
        <CreateViewDialog
          targetDatabase="alice"
          onCreate={vi.fn()}
          onCancel={vi.fn()}
        />
      );
      expect(screen.getByText('alice')).toBeInTheDocument();
    });

    it('disables Create until the name passes the catalog-safe rule', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      render(
        <CreateViewDialog
          targetDatabase="alice"
          onCreate={vi.fn()}
          onCancel={vi.fn()}
        />
      );
      const create = screen.getByRole('button', {name: 'Create'});
      expect(create).toBeDisabled();

      // Invalid: leading digit.
      await user.type(screen.getByLabelText('View name'), '9bad');
      expect(create).toBeDisabled();
      expect(screen.getByText(/3–63 characters/)).toBeInTheDocument();

      // Valid.
      await user.clear(screen.getByLabelText('View name'));
      await user.type(screen.getByLabelText('View name'), 'monthly_revenue');
      expect(create).toBeEnabled();
    });

    it('confirms with the trimmed valid name', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const onCreate = vi.fn();
      render(
        <CreateViewDialog
          targetDatabase="alice"
          onCreate={onCreate}
          onCancel={vi.fn()}
        />
      );
      await user.type(screen.getByLabelText('View name'), '  sales_view  ');
      await user.click(screen.getByRole('button', {name: 'Create'}));
      expect(onCreate).toHaveBeenCalledWith('sales_view');
    });

    it('locks Create + shows progress while busy', () => {
      render(
        <CreateViewDialog
          targetDatabase="alice"
          busy
          onCreate={vi.fn()}
          onCancel={vi.fn()}
        />
      );
      expect(screen.getByRole('button', {name: 'Creating…'})).toBeDisabled();
    });
  });
});

// ─── from QueryHistoryRow.test.tsx ───
describe('QueryHistoryRow', () => {
  function entry(overrides: Partial<QueryHistoryEntry> = {}): QueryHistoryEntry {
    return {
      queryExecutionId: 'q1',
      sql: 'SELECT region,\n  SUM(amount)\nFROM sales',
      database: 'alice',
      submittedAt: new Date().toISOString(),
      status: 'SUCCEEDED',
      dataScannedBytes: 2048,
      durationMs: 800,
      ...overrides
    };
  }

  describe('QueryHistoryRow', () => {
    it('renders the status, single-line SQL preview, and stats', () => {
      render(
        <QueryHistoryRow
          entry={entry()}
          onReopen={vi.fn()}
          onRerun={vi.fn()}
          rerunDisabled={false}
        />
      );
      expect(screen.getByText('Succeeded')).toBeInTheDocument();
      // Whitespace collapsed to a single line.
      expect(screen.getByText('SELECT region, SUM(amount) FROM sales')).toBeInTheDocument();
      expect(screen.getByText('2.0 KB scanned · 800 ms')).toBeInTheDocument();
    });

    it('fires onReopen / onRerun from the actions', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const onReopen = vi.fn();
      const onRerun = vi.fn();
      render(
        <QueryHistoryRow
          entry={entry()}
          onReopen={onReopen}
          onRerun={onRerun}
          rerunDisabled={false}
        />
      );
      await user.click(screen.getByRole('button', {name: /open this query/i}));
      await user.click(screen.getByRole('button', {name: /re-run this query/i}));
      expect(onReopen).toHaveBeenCalledTimes(1);
      expect(onRerun).toHaveBeenCalledTimes(1);
    });

    it('disables Re-run while a query is in flight', () => {
      render(
        <QueryHistoryRow
          entry={entry()}
          onReopen={vi.fn()}
          onRerun={vi.fn()}
          rerunDisabled
        />
      );
      expect(screen.getByRole('button', {name: /re-run this query/i})).toBeDisabled();
    });

    it('shows a neutral "Unknown" badge for a stale non-terminal entry', () => {
      render(
        <QueryHistoryRow
          entry={entry({status: 'RUNNING', dataScannedBytes: undefined, durationMs: undefined})}
          onReopen={vi.fn()}
          onRerun={vi.fn()}
          rerunDisabled={false}
        />
      );
      expect(screen.getByText('Unknown')).toBeInTheDocument();
    });
  });
});

// ─── from ResultTabs.test.tsx ───
describe('ResultTabs', () => {
  // The strip renders the label and keys on the execution id; the captured status is
  // the workspace's business, so these carry the bare shape the type requires.
  const status = (id: string): QueryStatus => ({queryExecutionId: id, state: 'SUCCEEDED'});
  const tabs: ResultTab[] = [
    {statementIndex: 0, executionId: 'q-1', label: '1 · SELECT a', status: status('q-1')},
    {statementIndex: 2, executionId: 'q-3', label: '3 · SELECT b', status: status('q-3')},
    {statementIndex: 3, executionId: 'q-4', label: '4 · SHOW TABLES', status: status('q-4')}
  ];

  function renderTabs(activeIndex = 0, onSelect = vi.fn(), onClose = vi.fn(), shown = tabs) {
    render(
      <ResultTabs
        tabs={shown}
        activeIndex={activeIndex}
        onSelect={onSelect}
        onClose={onClose}
      />
    );
    return onSelect;
  }

  describe('ResultTabs (SPEC-078 FR-007)', () => {
    it('renders one labeled tab per result set, in order, with the active tab selected', () => {
      renderTabs(1);
      const rendered = screen.getAllByRole('tab');
      expect(rendered.map((t) => t.textContent)).toEqual(['1 · SELECT a', '3 · SELECT b', '4 · SHOW TABLES']);
      expect(rendered[1]).toHaveAttribute('aria-selected', 'true');
      expect(rendered[0]).toHaveAttribute('aria-selected', 'false');
      expect(screen.getByRole('tablist', {name: 'Result tabs'})).toBeInTheDocument();
    });

    it('uses a roving tabindex — only the active tab is in the Tab sequence', () => {
      renderTabs(1);
      const rendered = screen.getAllByRole('tab');
      expect(rendered.map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
    });

    it('supports the WAI-ARIA tabs keyboard model (arrows wrap, Home/End jump)', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const onSelect = renderTabs(1);
      const rendered = screen.getAllByRole('tab');
      // The strip is controlled and `activeIndex` never moves here, so each key is sent from
      // the tab it names by focusing it first.
      const press = async (tab: HTMLElement, key: string) => {
        tab.focus();
        await user.keyboard(`{${key}}`);
      };

      await press(rendered[1], 'ArrowRight');
      expect(onSelect).toHaveBeenLastCalledWith(2);
      await press(rendered[1], 'ArrowLeft');
      expect(onSelect).toHaveBeenLastCalledWith(0);
      await press(rendered[2], 'ArrowRight'); // wraps
      expect(onSelect).toHaveBeenLastCalledWith(0);
      await press(rendered[1], 'Home');
      expect(onSelect).toHaveBeenLastCalledWith(0);
      await press(rendered[1], 'End');
      expect(onSelect).toHaveBeenLastCalledWith(2);
    });

    // Backspace too: it is the key a Mac keyboard labels "delete", and both other tab strips take it.
    it.each(['Delete', 'Backspace'])(
      'closes the focused tab on %s and hands focus to the tab after it',
      async (key) => {
        const user = userEvent.setup(USER_EVENT_OPTIONS);
        const onClose = vi.fn();
        renderTabs(1, vi.fn(), onClose);
        const rendered = screen.getAllByRole('tab');

        rendered[1].focus();
        await user.keyboard(`{${key}}`);

        expect(onClose).toHaveBeenCalledWith(1);
        expect(rendered[2]).toHaveFocus();
      }
    );

    // A click on a ✕ focuses the tab it sits in, and the close removes that tab. Closing a tab
    // that is not the shown one leaves the shown one shown, so focus goes there, not to a neighbour.
    it.each([
      ['the shown tab', '3 · SELECT b', 1, 2],
      ['another tab', '1 · SELECT a', 0, 1]
    ])('hands focus to the tab shown after a pointer close of %s', async (_, label, closed, heir) => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const onClose = vi.fn();
      renderTabs(1, vi.fn(), onClose);
      const rendered = screen.getAllByRole('tab');

      await user.click(screen.getByTitle(`Close ${label}`));

      expect(onClose).toHaveBeenCalledWith(closed);
      expect(rendered[heir]).toHaveFocus();
    });

    it('offers no way to close the last remaining tab', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const onClose = vi.fn();
      renderTabs(0, vi.fn(), onClose, tabs.slice(0, 1));

      screen.getByRole('tab').focus();
      await user.keyboard('{Delete}');

      expect(onClose).not.toHaveBeenCalled();
      expect(screen.queryByTitle(/^Close /)).not.toBeInTheDocument();
    });
  });
});

// ─── from ResultsPageSizeControl.test.tsx ───
describe('ResultsPageSizeControl', () => {
  function setup(props: Partial<React.ComponentProps<typeof ResultsPageSizeControl>> = {}) {
    const onCommit = vi.fn();
    const view = render(
      <ResultsPageSizeControl
        pageSize={100}
        onCommit={onCommit}
        {...props}
      />
    );
    return {onCommit, view, input: screen.getByLabelText('Rows per page')};
  }

  describe('ResultsPageSizeControl', () => {
    it('shows the current page size under the accessible name "Rows per page"', () => {
      const {input} = setup();
      expect(input).toHaveValue('100');
    });

    // Asserts the ASSOCIATION, not the presence of the sentence: a hint that renders
    // beside the input but describes nothing is invisible to a screen reader, and
    // "the text is on screen" passes either way.
    it('describes the control with the hint that it does not re-run the query', () => {
      const {input} = setup();
      const describedBy = input.getAttribute('aria-describedby');
      expect(describedBy).toBeTruthy();
      const hint = document.getElementById(describedBy as string);
      expect(hint).toHaveTextContent(/doesn’t re-run your query/i);
    });

    it('commits an in-range integer on Enter', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const {onCommit, input} = setup();
      await user.clear(input);
      await user.type(input, '250{Enter}');
      expect(onCommit).toHaveBeenCalledWith(250);
    });

    it('clamps out-of-range values to the bounds (FR-003)', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const {onCommit, input} = setup();
      await user.clear(input);
      await user.type(input, '0{Enter}');
      expect(onCommit).toHaveBeenCalledWith(MIN_RESULTS_PAGE_SIZE);
      expect(input).toHaveValue(String(MIN_RESULTS_PAGE_SIZE));

      await user.clear(input);
      await user.type(input, '5000{Enter}');
      expect(onCommit).toHaveBeenCalledWith(MAX_RESULTS_PAGE_SIZE);
      expect(input).toHaveValue(String(MAX_RESULTS_PAGE_SIZE));
    });

    it('reverts non-numeric, empty, and fractional input to the last valid value (FR-003)', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      for (const bad of ['abc', '', '2.5']) {
        const {onCommit, input, view} = setup();
        await user.clear(input);
        if (bad !== '') await user.type(input, bad);
        await user.tab();
        expect(onCommit).not.toHaveBeenCalled();
        expect(input).toHaveValue('100');
        view.unmount();
      }
    });

    it('re-syncs when the committed value changes externally (FR-004: one global value)', () => {
      const {view, input} = setup();
      view.rerender(
        <ResultsPageSizeControl
          pageSize={500}
          onCommit={vi.fn()}
        />
      );
      expect(input).toHaveValue('500');
    });

    it('has no axe violations, enabled or disabled (SPEC-045)', async () => {
      const {view} = setup();
      expect(await axe(view.container)).toHaveNoViolations();
      view.unmount();
      const {view: disabledView} = setup({disabled: true});
      expect(await axe(disabledView.container)).toHaveNoViolations();
    });
  });
});

// ─── from SavedQueriesPanel.test.tsx ───
describe('SavedQueriesPanel', () => {
  function sq(name: string, updatedAt: string, size = 128): SavedQuery {
    return {
      spaceId: 'personal',
      bucket: 'user-space',
      key: `alice/saved_queries/${name}.sql`,
      name,
      updatedAt,
      size
    };
  }

  const queries = [sq('Older', '2026-06-01T00:00:00.000Z'), sq('Newer', '2026-06-10T00:00:00.000Z')];

  const personal: QuerySpace = {
    id: 'personal',
    label: 'alice',
    bucket: 'user-space',
    rootPrefix: 'alice/',
    rootLabel: 'My Files'
  };

  function setup(over: Partial<Parameters<typeof SavedQueriesPanel>[0]> = {}) {
    const onClose = vi.fn();
    const onOpen = vi.fn();
    const onDelete = vi.fn();
    const loadMore = vi.fn();
    const onSelectSpace = vi.fn();
    const onRetry = vi.fn();
    const view = render(
      <SavedQueriesPanel
        open
        onClose={onClose}
        spaces={[personal]}
        space={personal}
        onSelectSpace={onSelectSpace}
        queries={queries}
        isLoading={false}
        error={null}
        hasMore={false}
        onLoadMore={loadMore}
        isLoadingMore={false}
        onRetry={onRetry}
        onOpen={onOpen}
        onOpenAndRun={vi.fn()}
        onDelete={onDelete}
        {...over}
      />
    );
    return {...view, onClose, onOpen, onDelete, loadMore, onSelectSpace, onRetry};
  }

  it('keeps S3’s own listing order, and re-sorts nothing', () => {
    setup();
    const names = screen.getAllByText(/Older|Newer/).map((n) => n.textContent);
    expect(names).toEqual(['Older', 'Newer']);
  });

  it('renders name + relative time + size, and NO SQL preview', () => {
    // FR-006: a `.sql` file carries no body until it is read, so a preview line would
    // mean a GetObject per row every time the drawer opens.
    setup();
    expect(screen.getByText('Older')).toBeInTheDocument();
    expect(screen.getAllByText('128 B').length).toBeGreaterThan(0);
    expect(screen.queryByText(/SELECT/i)).not.toBeInTheDocument();
  });

  it('Open fires onOpen with the whole record, key included', async () => {
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    const {onOpen} = setup();
    await user.click(screen.getAllByRole('button', {name: /open saved query/i})[0]);
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({key: 'alice/saved_queries/Older.sql'}));
  });

  it('shows a friendly empty state naming the space', () => {
    setup({queries: []});
    expect(screen.getByText('No saved queries in alice')).toBeInTheDocument();
  });

  it('keeps fetching rather than reading as empty while listing pages remain', () => {
    // SPEC-174 FR-002. An S3 page and a display page are different things: a listing
    // page of 25 keys can hold no `.sql` file at all, so a folder of CSVs must not be a
    // dead end — and must not be a "Load more" the user has to guess at either.
    const {loadMore} = setup({queries: [], hasMore: true});
    expect(screen.queryByText(/No saved queries in/)).not.toBeInTheDocument();
    expect(screen.getByText(/Loading saved queries/)).toBeInTheDocument();
    expect(loadMore).toHaveBeenCalled();
    // No pager over nothing while it fills.
    expect(screen.queryByRole('button', {name: 'Next'})).not.toBeInTheDocument();
  });

  it('shows a danger banner on error', () => {
    setup({error: 'access denied'});
    expect(screen.getByText(/Couldn’t load saved queries/)).toBeInTheDocument();
  });

  // ── SPEC-174 ──

  const team: QuerySpace = {
    id: 'teamspace',
    label: 'teamspace',
    bucket: 'shared-space',
    rootPrefix: 'teamspace/',
    rootLabel: 'teamspace'
  };

  it('renders a labelled space control listing exactly the spaces it was given, personal first', async () => {
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    const {onSelectSpace} = setup({spaces: [personal, team]});
    const select = screen.getByLabelText('Space');
    expect(
      within(select)
        .getAllByRole('option')
        .map((o) => o.textContent)
    ).toEqual(['alice', 'teamspace']);

    await user.selectOptions(select, 'teamspace');
    expect(onSelectSpace).toHaveBeenCalledWith('teamspace');
  });

  it('offers Retry on a failed listing', async () => {
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    const {onRetry} = setup({error: 'boom'});
    await user.click(screen.getByRole('button', {name: 'Retry'}));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('pages the filtered rows, not the listing’s keys', async () => {
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    // A folder of 30 files of which 12 are `.sql` reads `1–10 of 12`, never `of 30`.
    const twelve = Array.from({length: 12}, (_, i) => sq(`q${i}`, '2026-06-01T00:00:00.000Z'));
    setup({queries: twelve});
    expect(screen.getByText('1–10 of 12')).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Next'}));
    expect(screen.getByText('11–12 of 12')).toBeInTheDocument();
  });

  it('keeps the loaded rows and the pager when a FURTHER page fails', async () => {
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    // FR-002 AC5. A failed load-more used to replace the whole list with the banner: 20
    // rows and the pager vanished, and Retry was the only way back.
    const twelve = Array.from({length: 12}, (_, i) => sq(`q${i}`, '2026-06-01T00:00:00.000Z'));
    setup({queries: twelve, hasMore: true, error: 'throttled'});

    expect(screen.getByText(/Couldn’t load saved queries/)).toBeInTheDocument();
    expect(screen.getAllByRole('button', {name: /open saved query/i})).toHaveLength(10);
    // Prev/Next over what IS loaded; Next is not offered past it, because the error stops
    // the fill and the control could never advance.
    expect(screen.getByText('1–10 of 12+')).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Next'}));
    expect(screen.getByText('11–12 of 12+')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Next'})).toBeDisabled();
  });

  it('resets to page 1 when the drawer is reopened, and when the space changes', async () => {
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    // Asserted at the CALLER, because the hook's own reset test changes the key itself and
    // cannot fail when the panel stops changing it.
    const twelve = Array.from({length: 12}, (_, i) => sq(`q${i}`, '2026-06-01T00:00:00.000Z'));
    const props = {
      open: true,
      onClose: vi.fn(),
      spaces: [personal, team],
      space: personal,
      onSelectSpace: vi.fn(),
      queries: twelve,
      isLoading: false,
      error: null,
      hasMore: false,
      onLoadMore: vi.fn(),
      isLoadingMore: false,
      onRetry: vi.fn(),
      onOpen: vi.fn(),
      onOpenAndRun: vi.fn(),
      onDelete: vi.fn()
    };
    const {rerender} = render(<SavedQueriesPanel {...props} />);
    await user.click(screen.getByRole('button', {name: 'Next'}));
    expect(screen.getByText('11–12 of 12')).toBeInTheDocument();

    rerender(
      <SavedQueriesPanel
        {...props}
        open={false}
      />
    );
    rerender(<SavedQueriesPanel {...props} />);
    expect(screen.getByText('1–10 of 12')).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'Next'}));
    expect(screen.getByText('11–12 of 12')).toBeInTheDocument();
    rerender(
      <SavedQueriesPanel
        {...props}
        space={team}
      />
    );
    expect(screen.getByText('1–10 of 12')).toBeInTheDocument();
  });

  it('has no axe violations in its rows, empty and error states — each as DRIVEN', async () => {
    const {container: withRows} = setup();
    await expectContainerHasNoA11yViolations(withRows, COMPONENT_AXE_OPTIONS);

    const {container: empty} = setup({queries: []});
    await expectContainerHasNoA11yViolations(empty, COMPONENT_AXE_OPTIONS);

    const {container: failed} = setup({error: 'access denied'});
    await expectContainerHasNoA11yViolations(failed, COMPONENT_AXE_OPTIONS);
  });
});

// ─── from TableActionsMenu.test.tsx ───
describe('TableActionsMenu', () => {
  function items(over: Partial<Record<string, () => void>> = {}): TableMenuItem[] {
    return [
      {key: 'a', label: 'View data', onSelect: over.a ?? vi.fn()},
      {
        key: 'b',
        label: 'Drop table',
        onSelect: over.b ?? vi.fn(),
        danger: true,
        separatorBefore: true
      }
    ];
  }

  describe('TableActionsMenu', () => {
    it('is closed initially and opens on click', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      render(
        <TableActionsMenu
          tableName="sales"
          items={items()}
        />
      );
      const trigger = screen.getByRole('button', {name: 'Options for sales'});
      expect(trigger).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();

      await user.click(trigger);
      expect(trigger).toHaveAttribute('aria-expanded', 'true');
      expect(screen.getByRole('menu')).toBeInTheDocument();
    });

    it('fires the item onSelect and closes', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const onSelect = vi.fn();
      render(
        <TableActionsMenu
          tableName="sales"
          items={items({a: onSelect})}
        />
      );
      await user.click(screen.getByRole('button', {name: 'Options for sales'}));
      await user.click(screen.getByRole('menuitem', {name: 'View data'}));
      expect(onSelect).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });
  });
});

// ─── from QueryTabStrip.test.tsx ───
describe('QueryTabStrip', () => {
  const tabs: QueryTab[] = [
    {id: 'a', label: 'Query 1', sql: 'SELECT 1;'},
    {id: 'b', label: 'Monthly revenue', sql: 'SELECT 2;', savedQuery: LINK}
  ];

  function setup(over: Partial<Parameters<typeof QueryTabStrip>[0]> = {}) {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    const onNew = vi.fn();
    const onOpenHistory = vi.fn();
    render(
      <QueryTabStrip
        tabs={tabs}
        activeTabId="a"
        dirtyTabIds={new Set()}
        onSelect={onSelect}
        onClose={onClose}
        onNew={onNew}
        onOpenHistory={onOpenHistory}
        {...over}
      />
    );
    return {onSelect, onClose, onNew, onOpenHistory};
  }

  describe('QueryTabStrip', () => {
    it('renders one tab per query with the active one selected', () => {
      setup();
      const tablist = screen.getByRole('tablist', {name: 'Query tabs'});
      expect(tablist).toBeInTheDocument();
      expect(screen.getByRole('tab', {name: /Query 1/})).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByRole('tab', {name: /Monthly revenue/})).toHaveAttribute('aria-selected', 'false');
    });

    it('selects a tab on click and closes via the × control', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const {onSelect, onClose} = setup();
      await user.click(screen.getByRole('tab', {name: /Monthly revenue/}));
      expect(onSelect).toHaveBeenCalledWith('b');

      await user.click(screen.getByTitle('Close Monthly revenue'));
      expect(onClose).toHaveBeenCalledWith('b');
    });

    it('renders the global History button', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      const {onOpenHistory} = setup();
      await user.click(screen.getByRole('button', {name: 'History'}));
      expect(onOpenHistory).toHaveBeenCalledTimes(1);
    });

    it('shows a dirty marker on a linked tab with unsaved edits', () => {
      setup({dirtyTabIds: new Set(['b'])});
      expect(screen.getByLabelText('Unsaved changes')).toBeInTheDocument();
    });
  });
});

// ─── from QueryTabStrip.a11y.test.tsx ───
describe('QueryTabStrip.a11y', () => {
  const tabs: QueryTab[] = [
    {id: 't1', label: 'Query 1', sql: 'SELECT 1;'},
    {id: 't2', label: 'Revenue', sql: 'SELECT 2;', savedQuery: LINK},
    {id: 't3', label: 'Query 3', sql: ''}
  ];

  const noop = () => {};

  function strip(activeTabId = 't1') {
    return (
      <div>
        <QueryTabStrip
          tabs={tabs}
          activeTabId={activeTabId}
          dirtyTabIds={new Set(['t2'])}
          onSelect={noop}
          onClose={noop}
          onNew={noop}
          onOpenHistory={noop}
        />
        {/* The panel the tablist's `aria-controls` points at (lives in
            QueryWorkspace at runtime). */}
        <div
          role="tabpanel"
          id="query-tabpanel"
          aria-labelledby="query-tab-t1"
        />
      </div>
    );
  }

  describe('QueryTabStrip accessibility (SPEC-045 FR-004)', () => {
    it('exposes a tablist whose only children are tabs, linked to one tabpanel', () => {
      render(strip());
      const tablist = screen.getByRole('tablist', {name: 'Query tabs'});
      expect(tablist).toBeInTheDocument();

      const tabEls = screen.getAllByRole('tab');
      expect(tabEls).toHaveLength(3);
      // Every tab is a direct child of the tablist (aria-required-children) and links
      // to the single shared tabpanel.
      for (const tab of tabEls) {
        expect(tab.parentElement).toBe(tablist);
        expect(tab).toHaveAttribute('aria-controls', 'query-tabpanel');
      }
      expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'query-tabpanel');
    });
  });
});
