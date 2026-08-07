import {beforeEach, describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, within} from '@testing-library/react';
import {ColumnResizeHandle} from './ColumnResizeHandle';
import {COLUMN_RESIZE_STEP_PX, MAX_RESULTS_PAGE_SIZE, MIN_RESULTS_PAGE_SIZE} from './query.constants';
import {CreateViewDialog} from './CreateViewDialog';
import {axe} from 'vitest-axe';
import {EditorLayoutControl} from './EditorLayoutControl';
import {QueryHistoryRow} from './QueryHistoryRow';
import {ResultTabs} from './ResultTabs';
import {ResultsPageSizeControl} from './ResultsPageSizeControl';
import {SaveQueryDialog} from './SaveQueryDialog';
import {SavedQueriesPanel} from './SavedQueriesPanel';
import {TableActionsMenu} from './TableActionsMenu';
import type {TableMenuItem} from './TableActionsMenu';
import {QueryTabStrip} from './QueryTabStrip';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import type {QueryHistoryEntry, QueryTab, ResultTab, SavedQuery} from './query.types';

// ─── from ColumnResizeHandle.test.tsx ───
describe('ColumnResizeHandle', () => {
  function renderHandle(over: Partial<Parameters<typeof ColumnResizeHandle>[0]> = {}) {
    const props = {
      columnIndex: 2,
      columnName: 'revenue',
      width: 180,
      onResize: vi.fn(),
      onReset: vi.fn(),
      ...over
    };
    render(<ColumnResizeHandle {...props} />);
    return props;
  }

  describe('ColumnResizeHandle', () => {
    it('is an accessible vertical separator naming its column', () => {
      renderHandle();
      const handle = screen.getByRole('separator', {name: 'Resize column revenue'});
      expect(handle).toHaveAttribute('aria-orientation', 'vertical');
      expect(handle).toHaveAttribute('tabindex', '0');
    });

    it('drag resizes by the pointer delta from the gesture origin', () => {
      const {onResize} = renderHandle({columnIndex: 2, width: 180});
      const handle = screen.getByRole('separator');
      fireEvent.pointerDown(handle, {clientX: 100});
      fireEvent.pointerMove(window, {clientX: 140}); // +40
      expect(onResize).toHaveBeenLastCalledWith(2, 220);
      fireEvent.pointerMove(window, {clientX: 60}); // -40 from origin
      expect(onResize).toHaveBeenLastCalledWith(2, 140);
    });

    it('stops resizing after pointerup', () => {
      const onResize = vi.fn();
      renderHandle({onResize});
      const handle = screen.getByRole('separator');
      fireEvent.pointerDown(handle, {clientX: 100});
      fireEvent.pointerUp(window);
      onResize.mockClear();
      fireEvent.pointerMove(window, {clientX: 300});
      expect(onResize).not.toHaveBeenCalled();
    });

    it('double-click resets the column', () => {
      const {onReset} = renderHandle({columnIndex: 2});
      fireEvent.doubleClick(screen.getByRole('separator'));
      expect(onReset).toHaveBeenCalledWith(2);
    });

    it('Arrow Right / Left adjust the width by the keyboard step', () => {
      const {onResize} = renderHandle({columnIndex: 2, width: 180});
      const handle = screen.getByRole('separator');
      fireEvent.keyDown(handle, {key: 'ArrowRight'});
      expect(onResize).toHaveBeenLastCalledWith(2, 180 + COLUMN_RESIZE_STEP_PX);
      fireEvent.keyDown(handle, {key: 'ArrowLeft'});
      expect(onResize).toHaveBeenLastCalledWith(2, 180 - COLUMN_RESIZE_STEP_PX);
    });
  });
});

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

    it('disables Create until the name passes the catalog-safe rule', () => {
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
      fireEvent.change(screen.getByLabelText('View name'), {
        target: {value: '9bad'}
      });
      expect(create).toBeDisabled();
      expect(screen.getByText(/3–63 characters/)).toBeInTheDocument();

      // Valid.
      fireEvent.change(screen.getByLabelText('View name'), {
        target: {value: 'monthly_revenue'}
      });
      expect(create).toBeEnabled();
    });

    it('confirms with the trimmed valid name', () => {
      const onCreate = vi.fn();
      render(
        <CreateViewDialog
          targetDatabase="alice"
          onCreate={onCreate}
          onCancel={vi.fn()}
        />
      );
      fireEvent.change(screen.getByLabelText('View name'), {
        target: {value: '  sales_view  '}
      });
      fireEvent.click(screen.getByRole('button', {name: 'Create'}));
      expect(onCreate).toHaveBeenCalledWith('sales_view');
    });

    it('does not confirm an invalid name on Enter', () => {
      const onCreate = vi.fn();
      render(
        <CreateViewDialog
          targetDatabase="alice"
          onCreate={onCreate}
          onCancel={vi.fn()}
        />
      );
      const input = screen.getByLabelText('View name');
      fireEvent.change(input, {target: {value: 'Bad-Name'}});
      fireEvent.keyDown(input, {key: 'Enter'});
      expect(onCreate).not.toHaveBeenCalled();
    });

    it('cancels with no create', () => {
      const onCancel = vi.fn();
      const onCreate = vi.fn();
      render(
        <CreateViewDialog
          targetDatabase="alice"
          onCreate={onCreate}
          onCancel={onCancel}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalled();
      expect(onCreate).not.toHaveBeenCalled();
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

// ─── from EditorLayoutControl.test.tsx ───
describe('EditorLayoutControl', () => {
  describe('EditorLayoutControl', () => {
    it('renders the three options in a labeled group', () => {
      render(
        <EditorLayoutControl
          preset="even"
          onChange={() => {}}
        />
      );
      const group = screen.getByRole('group', {name: 'Editor and results layout'});
      expect(group).toBeInTheDocument();
      expect(screen.getByRole('button', {name: /grow the editor/i})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: /split editor and results evenly/i})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: /grow the results/i})).toBeInTheDocument();
    });

    it('marks only the selected option as pressed', () => {
      render(
        <EditorLayoutControl
          preset="results"
          onChange={() => {}}
        />
      );
      expect(screen.getByRole('button', {name: /grow the results/i})).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('button', {name: /grow the editor/i})).toHaveAttribute('aria-pressed', 'false');
      expect(screen.getByRole('button', {name: /split editor and results evenly/i})).toHaveAttribute(
        'aria-pressed',
        'false'
      );
    });

    it('reports the clicked preset', () => {
      const onChange = vi.fn();
      render(
        <EditorLayoutControl
          preset="even"
          onChange={onChange}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: /grow the editor/i}));
      expect(onChange).toHaveBeenCalledWith('editor');
    });

    it('is keyboard-operable: options are focusable native buttons', () => {
      const onChange = vi.fn();
      render(
        <EditorLayoutControl
          preset="even"
          onChange={onChange}
        />
      );
      const editorOption = screen.getByRole('button', {name: /grow the editor/i});
      // Native <button type="button"> — Enter/Space activation comes for free;
      // assert it is genuinely focusable and activation reports the preset.
      editorOption.focus();
      expect(editorOption).toHaveFocus();
      fireEvent.click(editorOption);
      expect(onChange).toHaveBeenCalledWith('editor');
    });

    it('has no axe violations', async () => {
      const {container} = render(
        <EditorLayoutControl
          preset="even"
          onChange={() => {}}
        />
      );
      expect(await axe(container)).toHaveNoViolations();
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

    it('fires onReopen / onRerun from the actions', () => {
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
      fireEvent.click(screen.getByRole('button', {name: /open this query/i}));
      fireEvent.click(screen.getByRole('button', {name: /re-run this query/i}));
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
  const tabs: ResultTab[] = [
    {statementIndex: 0, executionId: 'q-1', label: '1 · SELECT a'},
    {statementIndex: 2, executionId: 'q-3', label: '3 · SELECT b'},
    {statementIndex: 3, executionId: 'q-4', label: '4 · SHOW TABLES'}
  ];

  function renderTabs(activeIndex = 0, onSelect = vi.fn()) {
    render(
      <ResultTabs
        tabs={tabs}
        activeIndex={activeIndex}
        onSelect={onSelect}
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

    it('clicking a tab selects it', () => {
      const onSelect = renderTabs(0);
      fireEvent.click(screen.getByRole('tab', {name: /SHOW TABLES/}));
      expect(onSelect).toHaveBeenCalledWith(2);
    });

    it('uses a roving tabindex — only the active tab is in the Tab sequence', () => {
      renderTabs(1);
      const rendered = screen.getAllByRole('tab');
      expect(rendered.map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
    });

    it('supports the WAI-ARIA tabs keyboard model (arrows wrap, Home/End jump)', () => {
      const onSelect = renderTabs(1);
      const rendered = screen.getAllByRole('tab');

      fireEvent.keyDown(rendered[1], {key: 'ArrowRight'});
      expect(onSelect).toHaveBeenLastCalledWith(2);
      fireEvent.keyDown(rendered[1], {key: 'ArrowLeft'});
      expect(onSelect).toHaveBeenLastCalledWith(0);
      fireEvent.keyDown(rendered[2], {key: 'ArrowRight'}); // wraps
      expect(onSelect).toHaveBeenLastCalledWith(0);
      fireEvent.keyDown(rendered[1], {key: 'Home'});
      expect(onSelect).toHaveBeenLastCalledWith(0);
      fireEvent.keyDown(rendered[1], {key: 'End'});
      expect(onSelect).toHaveBeenLastCalledWith(2);
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

    it('commits an in-range integer on Enter', () => {
      const {onCommit, input} = setup();
      fireEvent.change(input, {target: {value: '250'}});
      fireEvent.keyDown(input, {key: 'Enter'});
      expect(onCommit).toHaveBeenCalledWith(250);
    });

    it('commits on blur, not per keystroke (FR-002)', () => {
      const {onCommit, input} = setup();
      fireEvent.change(input, {target: {value: '4'}});
      fireEvent.change(input, {target: {value: '42'}});
      expect(onCommit).not.toHaveBeenCalled();
      fireEvent.blur(input);
      expect(onCommit).toHaveBeenCalledTimes(1);
      expect(onCommit).toHaveBeenCalledWith(42);
    });

    it('clamps out-of-range values to the bounds (FR-003)', () => {
      const {onCommit, input} = setup();
      fireEvent.change(input, {target: {value: '0'}});
      fireEvent.keyDown(input, {key: 'Enter'});
      expect(onCommit).toHaveBeenCalledWith(MIN_RESULTS_PAGE_SIZE);
      expect(input).toHaveValue(String(MIN_RESULTS_PAGE_SIZE));

      fireEvent.change(input, {target: {value: '5000'}});
      fireEvent.keyDown(input, {key: 'Enter'});
      expect(onCommit).toHaveBeenCalledWith(MAX_RESULTS_PAGE_SIZE);
      expect(input).toHaveValue(String(MAX_RESULTS_PAGE_SIZE));
    });

    it('reverts non-numeric, empty, and fractional input to the last valid value (FR-003)', () => {
      for (const bad of ['abc', '', '2.5']) {
        const {onCommit, input, view} = setup();
        fireEvent.change(input, {target: {value: bad}});
        fireEvent.blur(input);
        expect(onCommit).not.toHaveBeenCalled();
        expect(input).toHaveValue('100');
        view.unmount();
      }
    });

    it('Escape abandons the draft without committing', () => {
      const {onCommit, input} = setup();
      fireEvent.change(input, {target: {value: '7'}});
      fireEvent.keyDown(input, {key: 'Escape'});
      expect(input).toHaveValue('100');
      expect(onCommit).not.toHaveBeenCalled();
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

    it('is rendered but non-interactive when disabled (FR-002: never hidden)', () => {
      const {input} = setup({disabled: true});
      expect(input).toBeDisabled();
      expect(input).toHaveValue('100');
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

// ─── from SaveQueryDialog.test.tsx ───
describe('SaveQueryDialog', () => {
  const existing: SavedQuery[] = [
    {
      id: 'sq-a',
      name: 'Monthly revenue',
      sql: 'SELECT 1',
      database: 'alice',
      createdAt: '2026-06-01T00:00:00.000Z',
      updatedAt: '2026-06-01T00:00:00.000Z'
    }
  ];

  function setup(over: Partial<Parameters<typeof SaveQueryDialog>[0]> = {}) {
    const onSave = vi.fn();
    const onCancel = vi.fn();
    render(
      <SaveQueryDialog
        initialName=""
        savedQueries={existing}
        onSave={onSave}
        onCancel={onCancel}
        {...over}
      />
    );
    return {onSave, onCancel};
  }

  describe('SaveQueryDialog', () => {
    it('disables Save until the name is non-empty, then saves a new query', () => {
      const {onSave} = setup();
      const save = screen.getByRole('button', {name: 'Save'});
      expect(save).toBeDisabled();

      fireEvent.change(screen.getByLabelText('Name'), {
        target: {value: '  Quarterly  '}
      });
      expect(save).toBeEnabled();
      fireEvent.click(save);

      // New (unlinked) save → targetId null, name trimmed.
      expect(onSave).toHaveBeenCalledWith({name: 'Quarterly', targetId: null});
    });

    it('pre-fills the name on re-save and updates in place (own name, no collision)', () => {
      const {onSave} = setup({initialName: 'Monthly revenue', linkedId: 'sq-a'});
      expect(screen.getByLabelText('Name')).toHaveValue('Monthly revenue');

      fireEvent.click(screen.getByRole('button', {name: 'Save'}));
      expect(onSave).toHaveBeenCalledWith({
        name: 'Monthly revenue',
        targetId: 'sq-a'
      });
    });

    it('warns and confirms when the name collides with a different query', () => {
      const {onSave} = setup();
      fireEvent.change(screen.getByLabelText('Name'), {
        target: {value: 'monthly revenue'} // case-insensitive match of sq-a
      });
      fireEvent.click(screen.getByRole('button', {name: 'Save'}));

      // Overwrite-confirm step, not yet saved.
      expect(screen.getByRole('alertdialog', {name: /confirm replace saved query/i})).toBeInTheDocument();
      expect(onSave).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole('button', {name: 'Replace'}));
      expect(onSave).toHaveBeenCalledWith({
        name: 'monthly revenue',
        targetId: 'sq-a' // overwrites the existing one
      });
    });

    it('Cancel in the overwrite step returns to the prompt without saving', () => {
      const {onSave} = setup();
      fireEvent.change(screen.getByLabelText('Name'), {
        target: {value: 'Monthly revenue'}
      });
      fireEvent.click(screen.getByRole('button', {name: 'Save'}));
      fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));

      expect(onSave).not.toHaveBeenCalled();
      expect(screen.getByLabelText('Name')).toBeInTheDocument(); // back to prompt
    });

    it('Cancel closes the dialog', () => {
      const {onCancel} = setup();
      fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalled();
    });
  });
});

// ─── from SavedQueriesPanel.test.tsx ───
describe('SavedQueriesPanel', () => {
  function sq(id: string, name: string, updatedAt: string): SavedQuery {
    return {
      id,
      name,
      sql: 'SELECT 1',
      database: 'alice',
      createdAt: '2026-06-01T00:00:00.000Z',
      updatedAt
    };
  }

  const queries = [sq('a', 'Older', '2026-06-01T00:00:00.000Z'), sq('b', 'Newer', '2026-06-10T00:00:00.000Z')];

  function setup(over: Partial<Parameters<typeof SavedQueriesPanel>[0]> = {}) {
    const onClose = vi.fn();
    const onOpen = vi.fn();
    const onDelete = vi.fn();
    render(
      <SavedQueriesPanel
        open
        onClose={onClose}
        queries={queries}
        isLoading={false}
        error={null}
        onOpen={onOpen}
        onDelete={onDelete}
        {...over}
      />
    );
    return {onClose, onOpen, onDelete};
  }

  describe('SavedQueriesPanel', () => {
    it('renders nothing when closed', () => {
      setup({open: false});
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('lists saved queries most-recently-updated first', () => {
      setup();
      const names = screen.getAllByText(/Older|Newer/).map((n) => n.textContent);
      expect(names).toEqual(['Newer', 'Older']);
    });

    it('Open fires onOpen with the query', () => {
      const {onOpen} = setup();
      // The first card is "Newer" (b).
      fireEvent.click(screen.getAllByRole('button', {name: /open saved query/i})[0]);
      expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({id: 'b'}));
    });

    it('Delete confirms, then fires onDelete with the id', () => {
      const {onDelete} = setup();
      fireEvent.click(screen.getAllByRole('button', {name: /delete saved query/i})[0]);
      const dialog = screen.getByRole('alertdialog', {
        name: /confirm delete saved query/i
      });
      fireEvent.click(within(dialog).getByRole('button', {name: 'Delete'}));
      expect(onDelete).toHaveBeenCalledWith('b');
    });

    it('shows a friendly empty state', () => {
      setup({queries: []});
      expect(screen.getByText('No saved queries yet')).toBeInTheDocument();
    });

    it('shows a danger banner on error', () => {
      setup({error: 'access denied'});
      expect(screen.getByText(/Couldn’t load saved queries/)).toBeInTheDocument();
    });
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
    it('is closed initially and opens on click', () => {
      render(
        <TableActionsMenu
          tableName="sales"
          items={items()}
        />
      );
      const trigger = screen.getByRole('button', {name: 'Options for sales'});
      expect(trigger).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();

      fireEvent.click(trigger);
      expect(trigger).toHaveAttribute('aria-expanded', 'true');
      expect(screen.getByRole('menu')).toBeInTheDocument();
    });

    it('fires the item onSelect and closes', () => {
      const onSelect = vi.fn();
      render(
        <TableActionsMenu
          tableName="sales"
          items={items({a: onSelect})}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Options for sales'}));
      fireEvent.click(screen.getByRole('menuitem', {name: 'View data'}));
      expect(onSelect).toHaveBeenCalled();
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });

    it('closes on Escape and on outside click', () => {
      render(
        <div>
          <button>outside</button>
          <TableActionsMenu
            tableName="sales"
            items={items()}
          />
        </div>
      );
      const open = () => fireEvent.click(screen.getByRole('button', {name: 'Options for sales'}));

      open();
      fireEvent.keyDown(screen.getByRole('menu'), {key: 'Escape'});
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();

      open();
      fireEvent.mouseDown(screen.getByRole('button', {name: 'outside'}));
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });

    it('moves focus between items with arrow keys', () => {
      render(
        <TableActionsMenu
          tableName="sales"
          items={items()}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Options for sales'}));

      const first = screen.getByRole('menuitem', {name: 'View data'});
      const second = screen.getByRole('menuitem', {name: 'Drop table'});
      expect(first).toHaveFocus(); // first item focused on open

      fireEvent.keyDown(screen.getByRole('menu'), {key: 'ArrowDown'});
      expect(second).toHaveFocus();
      fireEvent.keyDown(screen.getByRole('menu'), {key: 'ArrowUp'});
      expect(first).toHaveFocus();
    });
  });
});

// ─── from QueryTabStrip.test.tsx ───
describe('QueryTabStrip', () => {
  const tabs: QueryTab[] = [
    {id: 'a', label: 'Query 1', sql: 'SELECT 1;'},
    {id: 'b', label: 'Monthly revenue', sql: 'SELECT 2;', savedQueryId: 'sq-1'}
  ];

  function setup(over: Partial<Parameters<typeof QueryTabStrip>[0]> = {}) {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    const onNew = vi.fn();
    const onOpenSaved = vi.fn();
    const onOpenHistory = vi.fn();
    render(
      <QueryTabStrip
        tabs={tabs}
        activeTabId="a"
        dirtyTabIds={new Set()}
        onSelect={onSelect}
        onClose={onClose}
        onNew={onNew}
        onOpenSaved={onOpenSaved}
        onOpenHistory={onOpenHistory}
        {...over}
      />
    );
    return {onSelect, onClose, onNew, onOpenSaved, onOpenHistory};
  }

  describe('QueryTabStrip', () => {
    it('renders one tab per query with the active one selected', () => {
      setup();
      const tablist = screen.getByRole('tablist', {name: 'Query tabs'});
      expect(tablist).toBeInTheDocument();
      expect(screen.getByRole('tab', {name: /Query 1/})).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByRole('tab', {name: /Monthly revenue/})).toHaveAttribute('aria-selected', 'false');
    });

    it('selects a tab on click and closes via the × control', () => {
      const {onSelect, onClose} = setup();
      fireEvent.click(screen.getByRole('tab', {name: /Monthly revenue/}));
      expect(onSelect).toHaveBeenCalledWith('b');

      fireEvent.click(screen.getByTitle('Close Monthly revenue'));
      expect(onClose).toHaveBeenCalledWith('b');
    });

    it('clicking × does not also select the tab', () => {
      const {onSelect, onClose} = setup();
      fireEvent.click(screen.getByTitle('Close Query 1'));
      expect(onClose).toHaveBeenCalledWith('a');
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('always-enabled + button calls onNew', () => {
      const {onNew} = setup();
      const plus = screen.getByRole('button', {name: 'New query tab'});
      expect(plus).toBeEnabled();
      fireEvent.click(plus);
      expect(onNew).toHaveBeenCalled();
    });

    it('hides the close control when only one tab remains', () => {
      setup({tabs: [tabs[0]]});
      expect(screen.queryByTitle(/Close/)).not.toBeInTheDocument();
    });

    it('renders the global Saved queries + History buttons', () => {
      const {onOpenSaved, onOpenHistory} = setup();
      fireEvent.click(screen.getByRole('button', {name: 'Saved queries'}));
      expect(onOpenSaved).toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', {name: 'History'}));
      expect(onOpenHistory).toHaveBeenCalled();
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
    {id: 't2', label: 'Revenue', sql: 'SELECT 2;', savedQueryId: 'sq1'},
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
          onOpenSaved={noop}
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
    it('multi-tab strip has no violations', async () => {
      // The closable tab's ✕ is a decorative, non-focusable pointer affordance
      // (not a nested <button>), so axe's `nested-interactive` rule runs clean here
      // — keyboard close stays available via the Delete key on the focused tab.
      await expectNoA11yViolations(strip(), COMPONENT_AXE_OPTIONS);
    });

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
