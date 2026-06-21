import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryTabStrip } from './QueryTabStrip';
import type { QueryTab } from './query.types';

const tabs: QueryTab[] = [
  { id: 'a', label: 'Query 1', sql: 'SELECT 1;' },
  { id: 'b', label: 'Monthly revenue', sql: 'SELECT 2;', savedQueryId: 'sq-1' },
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
    />,
  );
  return { onSelect, onClose, onNew, onOpenSaved, onOpenHistory };
}

describe('QueryTabStrip', () => {
  it('renders one tab per query with the active one selected', () => {
    setup();
    const tablist = screen.getByRole('tablist', { name: 'Query tabs' });
    expect(tablist).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Query 1/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: /Monthly revenue/ })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('selects a tab on click and closes via the × control', () => {
    const { onSelect, onClose } = setup();
    fireEvent.click(screen.getByRole('tab', { name: /Monthly revenue/ }));
    expect(onSelect).toHaveBeenCalledWith('b');

    fireEvent.click(screen.getByRole('button', { name: 'Close Monthly revenue' }));
    expect(onClose).toHaveBeenCalledWith('b');
  });

  it('clicking × does not also select the tab', () => {
    const { onSelect, onClose } = setup();
    fireEvent.click(screen.getByRole('button', { name: 'Close Query 1' }));
    expect(onClose).toHaveBeenCalledWith('a');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('always-enabled + button calls onNew', () => {
    const { onNew } = setup();
    const plus = screen.getByRole('button', { name: 'New query tab' });
    expect(plus).toBeEnabled();
    fireEvent.click(plus);
    expect(onNew).toHaveBeenCalled();
  });

  it('hides the close control when only one tab remains', () => {
    setup({ tabs: [tabs[0]] });
    expect(
      screen.queryByRole('button', { name: /Close/ }),
    ).not.toBeInTheDocument();
  });

  it('renders the global Saved queries + History buttons', () => {
    const { onOpenSaved, onOpenHistory } = setup();
    fireEvent.click(screen.getByRole('button', { name: 'Saved queries' }));
    expect(onOpenSaved).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    expect(onOpenHistory).toHaveBeenCalled();
  });

  it('shows a dirty marker on a linked tab with unsaved edits', () => {
    setup({ dirtyTabIds: new Set(['b']) });
    expect(screen.getByLabelText('Unsaved changes')).toBeInTheDocument();
  });
});
