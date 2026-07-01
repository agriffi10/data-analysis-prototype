import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi} from 'vitest';
import {RenameDialog} from './RenameDialog';

function setup(overrides?: {kind?: 'file' | 'folder'; isBusy?: boolean}) {
  const onRename = vi.fn();
  const onCancel = vi.fn();
  render(
    <RenameDialog
      kind={overrides?.kind ?? 'file'}
      currentName="report.pdf"
      isBusy={overrides?.isBusy}
      onRename={onRename}
      onCancel={onCancel}
    />
  );
  return {onRename, onCancel};
}

describe('RenameDialog', () => {
  it('prefills the base name (extension held separately) and disables Rename until it changes', () => {
    setup();
    const input = screen.getByLabelText(/new name/i) as HTMLInputElement;
    expect(input.value).toBe('report'); // ".pdf" is locked, not in the editable field
    expect(screen.getByText(/extension can’t be changed/i)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /^rename$/i})).toBeDisabled();
  });

  it('enables Rename for a changed, valid name and submits it with the extension re-appended', () => {
    const {onRename} = setup();
    fireEvent.change(screen.getByLabelText(/new name/i), {
      target: {value: 'final'}
    });
    const btn = screen.getByRole('button', {name: /^rename$/i});
    expect(btn).toBeEnabled();
    fireEvent.click(btn);
    expect(onRename).toHaveBeenCalledWith('final.pdf');
  });

  it('keeps the original extension even if the user types a different one', () => {
    const {onRename} = setup();
    fireEvent.change(screen.getByLabelText(/new name/i), {
      target: {value: 'final.txt'}
    });
    fireEvent.click(screen.getByRole('button', {name: /^rename$/i}));
    expect(onRename).toHaveBeenCalledWith('final.txt.pdf');
  });

  it('lets a folder name be edited in full (no locked extension)', () => {
    const onRename = vi.fn();
    render(
      <RenameDialog
        kind="folder"
        currentName="my.reports"
        onRename={onRename}
        onCancel={vi.fn()}
      />
    );
    const input = screen.getByLabelText(/new name/i) as HTMLInputElement;
    expect(input.value).toBe('my.reports');
    fireEvent.change(input, {target: {value: 'archive.2024'}});
    fireEvent.click(screen.getByRole('button', {name: /^rename$/i}));
    expect(onRename).toHaveBeenCalledWith('archive.2024');
  });

  it('rejects an invalid name (contains a slash) and keeps Rename disabled', () => {
    setup();
    fireEvent.change(screen.getByLabelText(/new name/i), {
      target: {value: 'a/b'}
    });
    expect(screen.getByRole('alert')).toHaveTextContent('/');
    expect(screen.getByRole('button', {name: /^rename$/i})).toBeDisabled();
  });

  it('cancels on Escape', () => {
    const {onCancel} = setup();
    fireEvent.keyDown(document, {key: 'Escape'});
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('shows progress and disables actions while busy', () => {
    setup({isBusy: true});
    expect(screen.getByRole('button', {name: /renaming/i})).toBeDisabled();
    expect(screen.getByRole('button', {name: /cancel/i})).toBeDisabled();
  });
});
