import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {SavedQueriesPanel} from './SavedQueriesPanel';
import type {SavedQuery} from './query.types';

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
