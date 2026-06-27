import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi} from 'vitest';
import {DeleteConfirmDialog} from './DeleteConfirmDialog';
import type {SelectableItem} from './selectionContext';

const file = (key: string): SelectableItem => ({type: 'file', key});
const folder = (prefix: string): SelectableItem => ({type: 'folder', prefix});

function setup(items: SelectableItem[], isDeleting = false) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <DeleteConfirmDialog
      items={items}
      isDeleting={isDeleting}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
  return {onConfirm, onCancel};
}

describe('DeleteConfirmDialog', () => {
  it('names a single file and warns it is irreversible', () => {
    setup([file('alice/report.pdf')]);
    const dialog = screen.getByRole('alertdialog', {name: /confirm delete/i});
    expect(dialog).toHaveTextContent(/delete .*report\.pdf/i);
    expect(dialog).toHaveTextContent(/can.t be undone/i);
  });

  it('describes a single folder as recursive', () => {
    setup([folder('alice/photos/')]);
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent(/folder .*photos.* and everything inside it/i);
  });

  it('shows the count and an item list for multiple items', () => {
    setup([file('alice/a.txt'), file('alice/b.txt'), folder('alice/c/')]);
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent(/delete 3 items/i);
    expect(dialog).toHaveTextContent('a.txt');
    expect(dialog).toHaveTextContent('b.txt');
    expect(dialog).toHaveTextContent('c');
    expect(dialog).toHaveTextContent(/folders are deleted along with all of their contents/i);
  });

  it('truncates a long list with an "and N more" line', () => {
    const items = Array.from({length: 7}, (_, i) => file(`alice/f${i}.txt`));
    setup(items);
    expect(screen.getByText(/and 2 more/i)).toBeInTheDocument();
  });

  it('confirms and cancels via the buttons', () => {
    const {onConfirm, onCancel} = setup([file('alice/a.txt')]);
    fireEvent.click(screen.getByRole('button', {name: /^delete$/i}));
    expect(onConfirm).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', {name: /cancel/i}));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('cancels on Escape', () => {
    const {onCancel} = setup([file('alice/a.txt')]);
    fireEvent.keyDown(document, {key: 'Escape'});
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('disables actions and shows progress while deleting', () => {
    setup([file('alice/a.txt')], true);
    expect(screen.getByRole('button', {name: /deleting/i})).toBeDisabled();
    expect(screen.getByRole('button', {name: /cancel/i})).toBeDisabled();
  });
});
