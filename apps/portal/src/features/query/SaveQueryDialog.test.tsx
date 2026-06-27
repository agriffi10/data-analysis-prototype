import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {SaveQueryDialog} from './SaveQueryDialog';
import type {SavedQuery} from './query.types';

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
